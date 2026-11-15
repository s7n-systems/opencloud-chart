"""Harness regression checks without Docker: python3 tests/e2e/test_harness.py."""
from pathlib import Path
import os
import subprocess
import tempfile
import unittest

RUN = Path(__file__).with_name('run.sh')
# Load the actual setup/functions without starting infrastructure.
SETUP = RUN.read_text().split('step "kind cluster"')[0]
SHARED_SETUP = (RUN.parent / 'shared' / 'run.sh').read_text().split('step "prerequisites"')[0]


class HarnessChecks(unittest.TestCase):
    def run_shell(self, body, keep='0', setup=SETUP):
        with tempfile.TemporaryDirectory() as directory:
            log = Path(directory) / 'kind.log'
            result = subprocess.run(
                ['bash', '-c', setup + '\nkind() { echo "$*" >> "$REVIEW_LOG"; };\n'
                 'python3() { echo 12345; };\n' + body],
                env={**os.environ, 'KEEP': keep, 'REVIEW_LOG': str(log)},
                capture_output=True, text=True, timeout=10,
            )
            # KEEP deliberately retains the work directory; remove this test's copy.
            for line in result.stdout.splitlines():
                if line.startswith('WORK='):
                    import shutil
                    shutil.rmtree(line.removeprefix('WORK='), ignore_errors=True)
            return result, log.read_text() if log.exists() else ''

    def test_failed_creation_does_not_delete_cluster(self):
        # The failing mock still logs, so a delete issued by cleanup would show up.
        result, log = self.run_shell('kind() { echo "$*" >> "$REVIEW_LOG"; [ "$1" != create ]; }; kind create cluster; created=1')
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(log, 'create cluster\n')

    def test_helm_test_cleanup_and_failure_logs(self):
        for script in (RUN, RUN.parent / 'shared' / 'run.sh'):
            snippet = 'if helm test' + script.read_text().split('if helm test', 1)[1].split('\nfi', 1)[0] + '\nfi\n'
            for status in (0, 7):
                with self.subTest(script=script.name, status=status):
                    body = '''
helm() {
  # Helm cannot retrieve logs after hook-succeeded has deleted the pod.
  case " $* " in *" --logs "*) return 1 ;; esac
  return HELM_STATUS
}
kubectl() { echo "failed pod logs" >&2; return 19; }
'''.replace('HELM_STATUS', str(status))
                    result, _ = self.run_shell(body + snippet + '\n:')
                    self.assertEqual(result.returncode, status, result.stderr)
                    if status == 0:
                        self.assertIn('ok   helm test', result.stdout)
                        self.assertNotIn('failed pod logs', result.stderr)
                    else:
                        self.assertIn('failed pod logs', result.stderr)
                        self.assertNotIn('ok   helm test', result.stdout)

    def test_owned_cluster_deleted_on_failure(self):
        result, log = self.run_shell('created=1; false')
        self.assertNotEqual(result.returncode, 0)
        self.assertRegex(log, r'^delete cluster --name opencloud-e2e-')

    def test_shared_cleanup_uses_kind_provider(self):
        from unittest.mock import patch
        with patch.dict(os.environ, {'KIND_EXPERIMENTAL_PROVIDER': 'podman'}):
            result, log = self.run_shell('''
kind() {
  if [ "$1" = get ]; then echo review-worker; else echo "kind $*" >> "$REVIEW_LOG"; fi
}
kubectl() { :; }
podman() { echo "podman $1 $2" >> "$REVIEW_LOG"; }
docker() { echo "wrong engine" >> "$REVIEW_LOG"; return 1; }
created=1
''', setup=SHARED_SETUP)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('podman exec review-worker', log)
        self.assertIn('kind delete cluster --name opencloud-shared-', log)
        self.assertNotIn('wrong engine', log)

    def test_shared_checks_preserve_failure_and_reap_forward(self):
        result, _ = self.run_shell('''
kubectl() { exec sleep 30; }
curl() { return 0; }
KC=http://keycloak
status=0
with_opencloud bash -c 'exit 7' || status=$?
[ "$status" = 7 ]
[ "${#pids[@]}" = 0 ]
! kill -0 "$FORWARD_PID" 2>/dev/null
''', setup=SHARED_SETUP)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_shared_waits_for_terminating_pods_before_readiness(self):
        result, log = self.run_shell('''
kubectl() {
  echo "$*" >> "$REVIEW_LOG"
  if [ "$3" = get ]; then echo opencloud-1; fi
}
wait_ready oc
''', setup=SHARED_SETUP)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertLess(log.index('wait --for=delete pod/opencloud-1'), log.index('wait --for=condition=Ready'))

    def test_shared_listing_does_not_depend_on_dav_response_order(self):
        import runpy
        import sys
        from types import SimpleNamespace
        from unittest.mock import patch
        backend = SimpleNamespace(OC='http://opencloud')
        with patch.dict(sys.modules, {'check': backend}), patch.object(sys, 'path', sys.path.copy()):
            module = runpy.run_path(str(RUN.parent / 'shared' / 'check_shared.py'))
        parent = '<response><href>/remote.php/webdav/shared-one/</href></response>'
        child = '<response><href>http://opencloud/remote.php/webdav/shared-one/file%20name.txt</href></response>'
        for responses in (parent + child, child + parent):
            backend.request = lambda *args, **kwargs: (207, f'<multistatus xmlns="DAV:">{responses}</multistatus>'.encode())
            self.assertEqual(module['names']('token', 'shared-one'), (207, {'file name.txt'}))

    def test_nfs_probe_keeps_lock_until_checker_finishes(self):
        import select
        import sys
        import yaml
        docs = yaml.safe_load_all((RUN.parent / 'shared' / 'nfs-check.yaml').read_text())
        script = next(d for d in docs if d['kind'] == 'ConfigMap')['data']['check.py']
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'check.py'
            path.write_text(script.replace('/shared/', directory + '/'))
            holder = subprocess.Popen([sys.executable, '-B', str(path), 'holder'], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            try:
                self.assertTrue(select.select([holder.stdout], [], [], 3)[0], 'holder did not take the lock')
                self.assertEqual(holder.stdout.readline().strip(), 'holder: lock taken')
                checker = subprocess.run([sys.executable, '-B', str(path), 'checker'], capture_output=True, text=True, timeout=10)
                self.assertEqual(checker.returncode, 0, checker.stdout + checker.stderr)
                self.assertIn('lock held by the other node is respected', checker.stdout)
                self.assertIn('50 immediate directory-link lookups in each direction', checker.stdout)
                self.assertEqual(holder.wait(timeout=3), 0)
            finally:
                if holder.poll() is None:
                    holder.kill()
                holder.communicate()

    def test_keep_stops_forward_but_retains_cluster(self):
        result, log = self.run_shell('''
created=1
echo "WORK=$work"
kubectl() { exec sleep 30; }
curl() { return 0; }
forward idp svc/keycloak 8080
[ "${#pids[@]}" = 1 ]
[ "${pids[0]}" = "$FORWARD_PID" ]
pid=$FORWARD_PID
cleanup
! kill -0 "$pid" 2>/dev/null
trap - EXIT
''', keep='1')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(log, '')
        self.assertIn('kept:', result.stdout)

    def test_checks_preserves_failure_and_reaps_forward(self):
        result, _ = self.run_shell('''
kubectl() { exec sleep 30; }
curl() { return 0; }
python3() {
  if [ "$1" = -c ]; then echo 12345; else return 7; fi
}
KC=http://keycloak
status=0
checks oc write marker || status=$?
[ "$status" = 7 ]
[ "${#pids[@]}" = 0 ]
! kill -0 "$FORWARD_PID" 2>/dev/null
''')
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_forward_timeout_fails(self):
        result, _ = self.run_shell('''
kubectl() { exec sleep 30; }
curl() { return 1; }
sleep() { :; }
forward idp svc/keycloak 8080
''')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('did not come up', result.stderr)

    def test_runtime_assertions_fail_closed(self):
        assertions = RUN.read_text().split('kubectl -n oc get pods -o json |', 1)[1].split('checks oc write fresh', 1)[0]
        assertions = 'kubectl -n oc get pods -o json |' + assertions
        # The first case is the positive control: without it, a broken snippet
        # would fail every case and the test would pass vacuously.
        for readonly, get_status, exec_status in [('true', 0, 0), ('false', 0, 0), ('true', 1, 0), ('true', 0, 1)]:
            with self.subTest(readonly=readonly, get_status=get_status, exec_status=exec_status):
                body = '''
unset -f python3
kubectl() {
  if [ "$3" = get ]; then
    echo '{"items":[{"metadata":{"name":"test"},"spec":{"containers":[{"name":"server","securityContext":{"readOnlyRootFilesystem":READONLY}}]}}]}'
    return GET_STATUS
  fi
  return EXEC_STATUS
}
'''.replace('READONLY', readonly).replace('GET_STATUS', str(get_status)).replace('EXEC_STATUS', str(exec_status))
                # In run.sh more commands follow these lines; a trailing ':' mimics
                # that, so a failure swallowed by `cmd && echo` cannot pass as the
                # shell's final exit status.
                result, _ = self.run_shell(body + assertions + '\n:')
                if (readonly, get_status, exec_status) == ('true', 0, 0):
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertIn('ok   every container has a read-only root filesystem', result.stdout)
                    self.assertIn('ok   no generated opencloud.yaml', result.stdout)
                else:
                    self.assertNotEqual(result.returncode, 0)


if __name__ == '__main__':
    unittest.main()
