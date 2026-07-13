# AWS Cost Savings Execution Design

## Objective

Reduce recurring AWS spend without stopping the production Lightsail WordPress site or deleting the designated overflow archive. Execute the six savings actions approved on 2026-07-13: migrate active authoritative DNS off Route 53, archive S3 data, remove obsolete snapshots, eliminate the widget's DynamoDB scans, retire `image-ocean.com`, and disable renewal for all dead domains.

## Approved scope

- Migrate 16 active Route 53 zones to Cloudflare using DNS-only records.
- Delete the stale `mycoffeeexplorer.com` Route 53 zone after confirming Cloudflare remains authoritative.
- Delete the unused `mergepdfnow.com` and retired `image-ocean.com` Route 53 zones.
- Disable auto-renew for `mergepdfnow.com`, `pic-ocean.com`, `samfrenchprogramming.com`, and `image-ocean.com`.
- Transition eligible objects in `ubuntu-pc-overflow` to S3 Glacier Flexible Retrieval. Preserve the bucket, encryption, public-access block, and abort-incomplete-multipart rule.
- Transition payloads in `ubuntu-clonezilla-backup-540646365808` and `workspace-backup-2-14-2026` from Glacier Flexible Retrieval to Deep Archive. Long restores are acceptable.
- Delete `FrenchProgrammingBlog-final-snapshot-20251207` and `acloudguru-manual-snap`. The production Lightsail instance is not touched.
- Change Claude Indicator task-loop discovery to read local project configuration only. It keeps the configured-project row but performs no DynamoDB import, connection, query, or scan.

## Approaches considered

### DNS

1. **Staged Cloudflare API migration, recommended and approved.** Create each zone, copy every non-NS/SOA record with proxying disabled, translate Route 53 aliases to flattened CNAMEs, change registrar nameservers, verify public answers, then delete the AWS zone.
2. Delete only stale zones. This is lower risk but leaves roughly $9/month of approved savings unrealized.
3. Transfer registration and DNS simultaneously. This adds registrar-lock and transfer risk and is outside the approved change.

### S3

1. **Lifecycle transition, recommended and approved.** It directly supports Standard/Standard-IA to Glacier Flexible Retrieval and Glacier Flexible Retrieval to Deep Archive without download or restore.
2. Rewrite objects with copy operations. This is request-heavy and cannot copy Glacier payloads without restoring them first.
3. Delete archives. This was not approved for S3; the user approved deleting only the two service snapshots.

### DynamoDB

1. **Local-config-only task-loop display, recommended and approved.** It eliminates all AWS reads while retaining project/model/cooldown information.
2. Add a project/time GSI. This duplicates the 112 MB table index and preserves a cloud dependency for a table with no writes in the last 30 days.
3. Poll less often. This reduces but does not eliminate an incorrect, non-paginated scan.

## Safety and data flow

### DNS cutover

1. Export Route 53 records and capture pre-change public DNS/HTTP evidence.
2. Create a Cloudflare zone in the existing account.
3. Create DNS-only Cloudflare records. Preserve TTLs where supported. Convert apex AWS aliases to DNS-only CNAMEs so Cloudflare flattening preserves apex behavior.
4. Compare record inventories before delegation.
5. Replace Route 53 Domains nameservers with the two Cloudflare nameservers.
6. Wait until public resolvers return Cloudflare nameservers and verify A/AAAA/CNAME/MX/TXT behavior plus HTTP endpoints.
7. Remove non-default records and delete the old Route 53 hosted zone.

If the existing Cloudflare credential cannot create zones, no active Route 53 zone is deleted or redelegated. Independent AWS savings continue while Cloudflare authentication is resolved through existing credentials or an authenticated dashboard session; no API key is requested from the user.

### S3 lifecycle

- `ubuntu-pc-overflow` receives a new enabled rule for objects larger than 131,071 bytes, transitioning at day 0 to `GLACIER`. Its existing seven-day abort rule remains unchanged. The current 215.159 GiB Standard-IA population is 39 days old, beyond its 30-day minimum.
- Each backup bucket retains its day-7 `GLACIER` transition and adds `DEEP_ARCHIVE` at day 97. Day 97 guarantees at least 90 days in Glacier Flexible Retrieval. Current payloads are already older than 97 days.
- Lifecycle execution is asynchronous. Completion is proven first by lifecycle configuration readback and later by object storage-class counts; configuration success is not misreported as immediate physical transition.

### Snapshot deletion

Immediately before deletion, verify names, ARNs, state `available`, source absence, and account. Delete only the two exact approved snapshots. Verify each service no longer returns it.

### Widget change

Add a failing test proving `fetch_task_loop_status()` does not access `boto3`, then remove the DynamoDB code path. The function continues returning enabled local project configuration with `last_task_ts=None`. Restart the local widget only after tests, review, commit, push, and remote parity checks.

## Verification

- Route 53: active-zone public delegation and records match Cloudflare; deleted zones are absent; 19 AWS hosted zones fall to zero after all 16 migrations and three deletions.
- Domains: all four requested domains report `AutoRenew=false`.
- S3: lifecycle configurations contain the exact preserved and new transitions; later storage-class summaries show Glacier/Deep Archive movement.
- Snapshots: exact Lightsail and RDS identifiers return not found and production Lightsail remains running.
- DynamoDB: test proves no AWS SDK access; live `ConsumedReadCapacityUnits` stops increasing after widget restart, allowing CloudWatch lag.
- Git: clean branch, tests recorded, commit pushed, and local/remote SHA parity confirmed.

## Non-goals

- No production Lightsail change.
- No S3 payload deletion.
- No registrar transfer.
- No Cloudflare proxy/CDN enablement during DNS migration.
- No Savings Plan, Reserved Instance, paid support, or new public mutation endpoint.

