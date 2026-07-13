# AWS Cost Savings Execution Design

## Objective

Reduce recurring AWS spend without stopping the production Lightsail WordPress site or deleting the designated overflow archive. Execute the six savings actions approved on 2026-07-13: migrate active authoritative DNS off Route 53, archive S3 data, remove obsolete snapshots, eliminate the widget's DynamoDB scans, retire `image-ocean.com`, and disable renewal for all dead domains.

## Approved scope

- Migrate 16 active Route 53 zones to Cloudflare using DNS-only records. Retain every unchanged Route 53 source zone through the hardened delayed-cleanup policy: a global floor of `2026-07-20T15:18:57.201000Z`, a rolling per-domain stale-cache clock, and a one-hour clean resolver window before deletion.
- Park `mergepdfnow.com`, `image-ocean.com`, `pic-ocean.com`, and `samfrenchprogramming.com` as empty Cloudflare Free zones using stored credentials, without purchasing a subscription, and change registrar nameservers to each assigned Cloudflare pair before deleting any corresponding Route 53 zone.
- Delete the stale `mycoffeeexplorer.com` Route 53 zone after confirming Cloudflare remains authoritative.
- Delete the unused `mergepdfnow.com` and retired `image-ocean.com` Route 53 zones only after their Cloudflare parking and delegation gates pass.
- Disable auto-renew for `mergepdfnow.com`, `pic-ocean.com`, `samfrenchprogramming.com`, and `image-ocean.com`.
- Transition eligible objects in `ubuntu-pc-overflow` to S3 Glacier Flexible Retrieval. Preserve the bucket, encryption, public-access block, and abort-incomplete-multipart rule.
- Transition payloads in `ubuntu-clonezilla-backup-540646365808` and `workspace-backup-2-14-2026` from Glacier Flexible Retrieval to Deep Archive. Long restores are acceptable.
- Delete `FrenchProgrammingBlog-final-snapshot-20251207` and `acloudguru-manual-snap`. The production Lightsail instance is not touched.
- Change Claude Indicator task-loop discovery to read local project configuration only. It keeps the configured-project row but performs no DynamoDB import, connection, query, or scan.

## Approaches considered

### DNS

1. **Staged Cloudflare API migration, recommended and approved.** Create each zone, copy every non-NS/SOA record with proxying disabled, translate Route 53 aliases to flattened CNAMEs, change registrar nameservers, verify the immediate cutover, and keep the AWS source zone serving through the hardened overlap and recursive-cache convergence gates before delayed deletion.
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

### Dead-domain parking

1. Create empty Cloudflare Free zones for `mergepdfnow.com`, `image-ocean.com`, `pic-ocean.com`, and `samfrenchprogramming.com` using stored credentials. Do not purchase a subscription or add content records.
2. Record each assigned Cloudflare nameserver pair and replace the registrar nameservers with that exact pair.
3. Require the registrar operation to succeed, Cloudflare to recognize the zone, and registrar, TLD-authoritative, and public nameserver checks to return the assigned pair.
4. Only after those checks pass may any corresponding Route 53 zone be emptied and deleted. `mycoffeeexplorer.com` is already safely authoritative on Cloudflare and requires the same authority recheck before its stale Route 53 zone is deleted.

`mergepdfnow.com` initially required a provisional exception to step 3 while
its registrar status was `clientHold`, which suppressed parent/public
delegation. That delete-under-hold path was not used. The first nameserver
operation failed while contact reachability was pending because the existing
registrant mailbox domain was unreachable. As the sole approved exception to
the default rule that DNS cost work must not change contact data, recovery
changed exactly the registrant `Email` field to an already-authenticated
existing Gmail profile. Pre/post hashes proved every other registrant field
and all admin, tech, billing, and privacy fields remained unchanged. The
contact operation succeeded, reachability completed, and `clientHold` cleared;
only then did the nameserver update retry succeed and the normal registrar,
parent, public, Cloudflare, and direct-authority gates pass before deletion.

Reusable recovery rule: keep registrar contact data immutable by default. A
contact-reachability exception may change only the registrant `Email` field to
an already-authenticated existing profile after proving the current mailbox is
unreachable. Hash the complete contact/privacy state before and after, require
all non-target fields to match, require contact-operation success,
reachability completion, and hold removal before retrying DNS changes, and
fail closed on any drift or incomplete gate. Never store the address or other
PII in repository documentation or operational reports.

### Active DNS cutover

1. Export Route 53 records and capture pre-change public DNS/HTTP evidence.
2. Create a Cloudflare zone in the existing account.
3. Create DNS-only Cloudflare records. Preserve TTLs where supported. Convert apex AWS aliases to DNS-only CNAMEs so Cloudflare flattening preserves apex behavior.
4. Compare record inventories before delegation.
5. Replace Route 53 Domains nameservers with the two Cloudflare nameservers.
6. Record when the registrar operation succeeds and perform immediate cutover verification: Cloudflare status, registrar/TLD/public nameservers, full record-manifest parity, HTTPS, and mail-sensitive records.
7. Keep every unchanged Route 53 source zone serving until at least the global cleanup floor, `2026-07-20T15:18:57.201000Z`, seven days after the last registrar success. The original 48-hour markers are historical only and do not authorize deletion.
8. Compute each domain's `effective_not_before` as `max(global floor, last old-NS observation + max(observed TTL, 172800 seconds) + 24 hours)`. Any later old-NS answer advances that domain's clock.
9. Only after that effective timestamp, run 13 rounds at five-minute intervals over one hour. In every round issue eight UDP and one TCP NS query to each of `1.1.1.1` and `8.8.8.8`. Require all 117 observations per resolver and domain to return only `bruce.ns.cloudflare.com` and `chloe.ns.cloudflare.com`; any old, empty, or unexpected answer resets the clean window.
10. At the first and final rounds, rerun the complete delayed gate: registrar nameservers, all 13 `.com` authorities, Cloudflare active/Free/price-0 state, exact record parity, zero proxying, both direct Cloudflare authorities, HTTPS/TLS or mail behavior, and unchanged Route 53 source hashes and counts.
11. Fail closed if any delayed-cleanup check fails or cannot be completed: leave the Route 53 zone and all source records intact. Only after the clean window and both complete gates pass may non-default records be removed and the old hosted zone deleted.

The immediate public-resolver checks were point-in-time observations, not proof
of complete recursive-cache convergence. Review sampling at
`2026-07-13T15:42:09Z`–`15:42:15Z` still found Route 53 nameserver shards for
eight domains. Five had quantified stale answers and TTLs; three were observed
qualitatively earlier. No empty or unrelated answer was seen. Durable private
state records the evidence and rolling clocks without storing credentials or
PII.

If the existing Cloudflare credential cannot create zones, no corresponding dead-domain Route 53 zone is deleted and no active Route 53 zone is deleted or redelegated. Independent AWS savings continue while Cloudflare authentication is resolved through existing credentials or an authenticated dashboard session; no API key is requested from the user.

### S3 lifecycle

- `ubuntu-pc-overflow` receives a new enabled rule for objects larger than 131,071 bytes, transitioning at day 0 to `GLACIER`. Its existing seven-day abort rule remains unchanged. The current 215.159 GiB Standard-IA population is 39 days old, beyond its 30-day minimum.
- Each backup bucket retains its day-7 `GLACIER` transition and adds `DEEP_ARCHIVE` at day 97. Day 97 guarantees at least 90 days in Glacier Flexible Retrieval. Current payloads are already older than 97 days.
- Lifecycle execution is asynchronous. Completion is proven first by lifecycle configuration readback and later by object storage-class counts; configuration success is not misreported as immediate physical transition.

### Snapshot deletion

Immediately before deletion, verify names, ARNs, state `available`, source absence, and account. Delete only the two exact approved snapshots. Verify each service no longer returns it.

### Widget change

Add a failing test proving `fetch_task_loop_status()` does not access `boto3`, then remove the DynamoDB code path. The function continues returning enabled local project configuration with `last_task_ts=None`. Restart the local widget only after tests, review, commit, push, and remote parity checks.

## Verification

- Route 53: immediate active-zone cutovers match Cloudflare while all 16 source zones remain intact. Delayed deletion begins only after the global floor, each rolling stale-cache clock, the 13-round resolver clean window, and both full gates pass; 19 AWS hosted zones eventually fall to zero after all 16 migrations and three completed stale-zone deletions.
- Domains: the four dead registrations are parked on empty Cloudflare Free zones with their assigned nameservers, and all four requested domains report `AutoRenew=false`.
- S3: lifecycle configurations contain the exact preserved and new transitions; later storage-class summaries show Glacier/Deep Archive movement.
- Snapshots: exact Lightsail and RDS identifiers return not found and production Lightsail remains running.
- DynamoDB: test proves no AWS SDK access; live `ConsumedReadCapacityUnits` stops increasing after widget restart, allowing CloudWatch lag.
- Git: clean branch, tests recorded, commit pushed, and local/remote SHA parity confirmed.

## Non-goals

- No production Lightsail change.
- No S3 payload deletion.
- No registrar transfer.
- No Cloudflare proxy/CDN enablement during DNS migration.
- No paid Cloudflare subscription and no Route 53 source-zone deletion before its global floor, rolling stale-cache clock, clean resolver window, and full delayed gates pass.
- No Savings Plan, Reserved Instance, paid support, or new public mutation endpoint.
