# Upgrading

Before an upgrade, back up config and data volumes, external service secrets and any S3 data. Test restoration. Review upstream application release notes as well as chart changes.

## Chart 0.7.2: Radicale 3.9.2

No steps are needed.

- **Radicale:** updated from 3.9.0 to 3.9.2, bug fixes only for the chart's configuration (`http_x_remote_user` authentication, file system storage). `getctag` is now derived from the sync token, so CalDAV and CardDAV clients may resynchronise collections once after the upgrade. A custom `radicale.config` with LDAP over TLS now sends the server's hostname as SNI. See the [changelog](https://github.com/Kozea/Radicale/blob/master/CHANGELOG.md).
- **Images:** Tika 4.2.0 pinned to a newer build of the same version.

## Chart 0.7.1: OpenCloud 9.2.0

- **Image:** OpenCloud rolling 9.2.0, pinned by digest. Review the upstream [release notes](https://github.com/opencloud-eu/opencloud/releases/tag/v9.2.0), including Reva's workpackages merge and security fixes.
- **Custom environment:** upstream removes the gateway create-home cache settings (`GATEWAY_CREATE_HOME_CACHE_*`). The chart does not set them; remove any custom overrides. New optional settings include `OC_CLAIM_MANAGED_SPACES_ENABLED`, `GRAPH_EXPORT_PERSONAL_DATA_RATE_LIMIT` and `OC_SPACE_IMAGE_THUMBNAILS_MAX_INPUT_IMAGE_FILE_SIZE`.
- **Chart configuration:** no values or template changes are introduced by this release. Existing 9.1.0 deployments keep their configuration. Runtime upgrade and data compatibility still need validation in your environment.

## Chart 0.7.0: helm test, NOTES and scheduling options

- **Radicale:** `radicale.enabled` now also controls whether OpenCloud advertises its CalDAV/CardDAV endpoints. It remains disabled by default, and the Keycloak/S3 example leaves it disabled too. Enable it explicitly if you use Radicale.
- **Shared NFS tests:** the default mount options now include `lookupcache=none` alongside `noac`, and the filesystem probe checks immediate directory-link visibility in both directions between nodes. User and system storage both run on every storage pod. Re-run the shared-storage suite against your own storage.
- **New:** `helm test` checks that OpenCloud and its companions answer. See Operations in the [README](../README.md#operations). `tests.enabled: false` removes the test pod.
- **New:** installs and upgrades print the public URL, the first sign-in and warnings for risky settings.
- **New:** `priorityClassName` and `sidecars` for OpenCloud, the frontend, yjs, Radicale and Tika; `persistence.retentionPolicy` and `radicale.persistence.retentionPolicy`; `service.loadBalancerClass`. Without them nothing changes.
- **NetworkPolicies:** with `tests.enabled` (the default), the chart's NetworkPolicies also admit the test pod to the ports it checks. `networkPolicy.enabled` now also adds policies for yjs and Tika, and admits yjs to OpenCloud's port 9200, which a restricted `networkPolicy.ingressFrom` blocked before.
- **Renamed:** `frontend.autoscaling.scaleDownStabilizationWindowSeconds` is replaced by `frontend.autoscaling.behavior`, whose default keeps the previous behavior. Move a custom value to `behavior.scaleDown.stabilizationWindowSeconds`; the old key fails the schema.
- **Autoscaling:** `targetMemoryUtilizationPercentage`, `metrics` and `behavior`. With CPU or memory targets, every frontend container, including sidecars and native sidecars, needs the matching resource request, or rendering fails.
- **New:** `frontend.podAntiAffinityPreset`; for yjs, Radicale and Tika `extraEnv`, `extraEnvVars`, `extraVolumes`, `extraVolumeMounts`, `extraInitContainers`, configurable probes and `serviceAccountName`.
- **Images:** Radicale v3.9.0 pinned to a newer build of the same version.

## Chart 0.6.0: themes

- **New:** `web.theme` adds a custom theme for the web UI from values. See [Theme](../README.md#theme). Without it nothing changes.

## Chart 0.5.0: network policies

- **New:** `networkPolicy.enabled` adds ingress NetworkPolicies for the OpenCloud pods. Off by default; recommended with `topology: split`. See [Security](../README.md#security).
- **New:** `networkPolicy.nats.podSelector` limits an external NATS in the release namespace to this release's OpenCloud pods. The chart rejects it when `nats.address` is a Kubernetes service name in another namespace.
- **Content Security Policy:** `media-src` allows `blob:`, as upstream does since OpenCloud 9.1, for motion photo playback. With `checkForUpdates: false`, `https://update.opencloud.eu/` is no longer allowed in `connect-src`.
- **OpenCloud 9.1.0:** security fixes in the web UI and newer Go dependencies; no changed settings. Read the upstream [release notes](https://github.com/opencloud-eu/opencloud/releases/tag/v9.1.0).
- **Images:** Radicale v3.9.0 pinned to a newer build of the same version.

## Chart 0.4.0: web extensions

- **New:** `web.extensions` installs web apps from images. See [Web extensions](../README.md#web-extensions).
- **Apps installed by hand:** if you copy apps to `/var/lib/opencloud/web/assets/apps` with `extraInitContainers`, move them to `web.extensions`. Once `web.extensions` is set, that directory is no longer served.
- **Tika:** updated to 4.2.0.

## Chart 0.3.0: OpenCloud 9.0

Read the upstream [upgrade notes](https://docs.opencloud.eu/docs/next/admin/maintenance/upgrade/upgrade-9.x.x). For the chart:

- **Generated config:** the init container updates `opencloud.yaml` on start. It adds the service account of the new `auth-guest` service and removes the old thumbnail settings. Existing values stay.
- **External service secrets:** `thumbnailsTransferToken` is no longer used. You can remove it from the Secret.
- **Thumbnails:** the cache moved to `thumbnails/cache` on the data volume. You can delete the old `thumbnails/files` folder.
- **Default quota:** if you set `GRAPH_SPACES_DEFAULT_QUOTA` through `extraEnv`, rename it to `OC_SPACES_DEFAULT_QUOTA`.
- **Guest access:** new and off by default. Enable it with `sharing.guestLinks`; it needs `smtp.enabled`.
- **Split topology:** `auth-guest` keeps its tokens on the data volume, so it runs in the storage pod, on the first pod only.
- **New uploads:** OpenCloud 9 also refuses moving or deleting a file while it is still processed after upload, with HTTP 425. Scripts that rename right after an upload must retry, as they already do for downloads.

## Chart 0.2.1: S3 value names

These names changed; no compatibility aliases are provided before chart 1.0:

| Previous value | New value |
| --- | --- |
| `storage.s3.accessKey` | `storage.s3.accessKeyId` |
| `storage.s3.accessKeySecretKey` | `storage.s3.accessKeyIdSecretKey` |

The default key read from an existing Secret also changed from `accessKey` to `accessKeyId`. Rename that Secret key or explicitly keep its old name in your existing values:

```yaml
storage:
  s3:
    accessKeyIdSecretKey: accessKey
```

## Changing topology

For non-shared storage, keep all persistence settings unchanged to retain the same claims.

To move from `single` to `split`:

1. Configure external OIDC and LDAP. Preserve existing service secrets with `scripts/service-secrets.py from-config`, then set `serviceSecrets.existingSecret`.
2. Deploy external NATS using the [scaling requirements](scaling.md#nats).
3. Stop new uploads and wait for pending work to finish.
4. Upgrade with `topology: split` and `nats.address`.

To return to `single`, set `topology: single`, `nats.address: ""`, `storagePods.replicas: 1` and `persistence.data.shared: false`. Keep external identity and service secrets. Queued events do not move between the external and embedded NATS servers.

### Entering or leaving shared storage

This is a storage migration, not just a topology change. Kubernetes cannot change StatefulSet volume-claim templates in place.

1. Stop traffic and all writers, and take a consistent backup.
2. Prepare the target claim. Copy data if necessary, preserving ownership and extended attributes. Shared mode requires suitable `ReadWriteMany` storage.
3. Set `persistence.data.existingClaim` to the claim holding the data. Set `shared` and the replica count for the target topology. Preserve the config claim as well.
4. Recreate the StatefulSet with the new volume layout during the maintenance window. Verify claim retention before deleting anything; do not delete the data claims.
5. Verify files, shares, search and uploads before reopening access. Retain the backup until the migration is confirmed.

A shared claim created by the chart has `helm.sh/resource-policy: keep`; it remains after the chart stops declaring it. Manage its ownership explicitly if it will be used by another release.
