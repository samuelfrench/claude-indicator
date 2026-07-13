# AWS Cost Savings Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Execute the approved Route 53, S3, snapshot, DynamoDB, and domain-renewal savings while preserving production services and proving every resulting state.

**Architecture:** External changes use one-resource-at-a-time preflight, mutation, and authoritative readback. The only source change is isolated in `claude-indicator`: its task-loop row becomes local-config-only and is developed test-first. Dead registrations are parked on empty Cloudflare Free zones before any corresponding AWS zone is deleted. Active DNS changes are staged through Cloudflare with proxying disabled, verified at cutover, kept in dual-provider overlap through a seven-day global floor plus a rolling stale-cache clock, and subjected to a one-hour clean resolver window before delayed Route 53 cleanup.

**Tech Stack:** AWS CLI v2, Cloudflare v4 API, Bash/JQ, Python 3.13, PySide6, unittest, Git/GitHub.

## Global Constraints

- AWS account must be exactly `540646365808` and IAM ARN must end in `user/ubuntu-desktop` before every mutation group.
- Keep `FrenchProgrammingBlog-New` running on Lightsail; do not modify its plan, IPs, disk, or DNS target.
- Never delete S3 payloads. Preserve SSE-S3 and all four public-access-block settings.
- Cloudflare migrated records must remain DNS-only (`proxied=false`) during cutover.
- Create empty Cloudflare Free zones for `mergepdfnow.com`, `image-ocean.com`, `pic-ocean.com`, and `samfrenchprogramming.com` using stored credentials, with no subscription purchase, and change registrar nameservers to the assigned Cloudflare pair before deleting any corresponding Route 53 zone.
- Do not delete any active Route 53 zone before `2026-07-20T15:18:57.201000Z`, seven days after the last registrar success. For each domain, use `effective_not_before = max(global floor, last old-NS observation + max(observed TTL, 172800 seconds) + 24 hours)`; any later stale answer advances the clock.
- After the effective timestamp, require 13 rounds at five-minute intervals over one hour. Each round issues eight UDP and one TCP NS query to each of `1.1.1.1` and `8.8.8.8`; all 117 observations per resolver and domain must return only the target Cloudflare nameservers. Reset the clean window on any old, empty, or unexpected answer.
- Run the complete delayed gate in rounds 1 and 13: registrar, all 13 `.com` authorities, Cloudflare active/Free/price-0 state, exact record parity, zero proxying, both direct Cloudflare authorities, HTTPS/TLS or mail, and unchanged Route 53 source hashes/counts. Any failed or incomplete gate leaves the source zone intact.
- Registrar contact data is immutable by default. The sole executed exception was `mergepdfnow.com`: after proving its existing registrant mailbox domain unreachable, recovery changed exactly the registrant `Email` field to an already-authenticated existing Gmail profile; pre/post hashes verified every other registrant field plus all admin, tech, billing, and privacy fields unchanged. Any comparable recovery must require contact-operation success, reachability completion, and hold removal before retrying nameservers, fail closed on any drift or incomplete gate, and never record the address or other PII. Do not apply this exception loosely to another domain.
- Disable auto-renew only for `mergepdfnow.com`, `pic-ocean.com`, `samfrenchprogramming.com`, and `image-ocean.com`.
- Use test-first development for production Python changes; commit and push all repository changes.
- Do not request or print credentials. Load existing tokens from `~/.env` without echoing values.
- Preserve unrelated user changes and pre-existing artifacts.

---

### Task 1: Correct the upstream headless-test baseline

**Files:**
- Modify: `tests/test_widget_ui.py`

**Interfaces:**
- Consumes: current tray-optional behavior in `ClaudeWidget` from commit `28b8970`
- Produces: deterministic tests covering both tray-present and tray-absent behavior without changing production code

- [ ] **Step 1: Reproduce and record the baseline**

Run:

```bash
python -m unittest discover -s tests -v
```

Expected baseline: 28 tests run; four failures/errors confined to stale tray and resize expectations in `tests/test_widget_ui.py`.

- [ ] **Step 2: Align tray tests with the current public behavior**

Import `QSystemTrayIcon`, extend `_make_inert_claude_widget()` with a
`tray_available` keyword, and make the availability patch part of the helper's
lifetime:

```python
from PySide6.QtWidgets import QApplication, QSystemTrayIcon

def _make_inert_claude_widget(self, *, tray_available: bool = False):
    patches = [
        patch.object(
            QSystemTrayIcon,
            "isSystemTrayAvailable",
            return_value=tray_available,
        ),
        patch.object(ClaudeWidget, "_setup_timers", lambda self: None),
        patch.object(ClaudeWidget, "_fetch_usage", lambda self, force=False: None),
        patch.object(ClaudeWidget, "_fetch_deploys", lambda self: None),
        patch.object(ClaudeWidget, "_fetch_runners", lambda self: None),
        patch.object(ClaudeWidget, "_fetch_task_loops", lambda self: None),
        patch.object(ClaudeWidget, "_fetch_task_groups", lambda self: None),
        patch.object(ClaudeWidget, "_fetch_cron_jobs", lambda self: None),
        patch.object(ClaudeWidget, "_update_system_metrics", lambda self: None),
        patch.object(ClaudeWidget, "_refresh_codex_usage", lambda self: None),
    ]
    for active_patch in patches:
        active_patch.start()
        self.addCleanup(active_patch.stop)
    widget = ClaudeWidget()
    self.addCleanup(widget.deleteLater)
    return widget
```

Replace the stale minimize assertion with explicit tray-present and
tray-absent coverage:

```python
def test_claude_header_minimize_button_toggles_from_tray(self):
    widget = self._make_inert_claude_widget(tray_available=True)
    calls = []
    widget._toggle_from_tray = lambda: calls.append("toggle")

    widget._minimize_btn.mousePressEvent(None)

    self.assertEqual(calls, ["toggle"])

def test_claude_header_minimize_button_closes_without_tray(self):
    widget = self._make_inert_claude_widget(tray_available=False)
    calls = []
    widget.close = lambda: calls.append("close")

    widget._minimize_btn.mousePressEvent(None)

    self.assertEqual(calls, ["close"])
```

Construct tray-dependent close/action tests with
`tray_available=True`. In the layout-growth test call `widget.adjustSize()`
after setting empty data and again after adding the model limit, before each
`QApplication.processEvents()`. Do not modify `claude_widget.py` in this task.

- [ ] **Step 3: Verify the corrected baseline**

Run:

```bash
python -m unittest discover -s tests -v
```

Expected: 28 tests pass with zero failures/errors.

- [ ] **Step 4: Commit**

```bash
git add tests/test_widget_ui.py
git commit -m "test: align widget tests with tray-optional behavior"
```

### Task 2: Remove DynamoDB polling from Claude Indicator

**Files:**
- Modify: `claude_widget.py:961-1012`
- Modify: `tests/test_widget_ui.py`
- Modify: `TODO.md`

**Interfaces:**
- Consumes: `PROJECTS_JSON_PATH` and the existing `TaskLoopInfo` model
- Produces: `fetch_task_loop_status() -> list[TaskLoopInfo]` using local JSON only, never importing or calling `boto3`

- [ ] **Step 1: Write the failing test**

Add a test that writes an enabled project configuration to a temporary file, patches `PROJECTS_JSON_PATH`, installs a spy `boto3` module, calls `fetch_task_loop_status()`, asserts configured name/model/effort/cooldown values, asserts `last_task_ts is None`, and asserts the spy's `resource` method was never called.

Use this exact test shape and imports:

```python
import json
import sys
from types import ModuleType
from unittest.mock import Mock, patch

import claude_widget

def test_task_loop_status_reads_local_config_without_aws(self):
    config = {
        "honey-explorer": {
            "autonomous": {
                "enabled": True,
                "model": "claude-opus-4-6",
                "effort": "high",
                "cooldown_minutes": 10,
            }
        },
        "disabled-project": {"autonomous": {"enabled": False}},
    }
    fake_boto3 = ModuleType("boto3")
    fake_boto3.resource = Mock()
    fake_dynamodb = ModuleType("boto3.dynamodb")
    fake_conditions = ModuleType("boto3.dynamodb.conditions")
    fake_conditions.Key = Mock()

    with tempfile.TemporaryDirectory() as tmp:
        config_path = Path(tmp) / "projects.json"
        config_path.write_text(json.dumps(config))
        with (
            patch.object(claude_widget, "PROJECTS_JSON_PATH", config_path),
            patch.dict(
                sys.modules,
                {
                    "boto3": fake_boto3,
                    "boto3.dynamodb": fake_dynamodb,
                    "boto3.dynamodb.conditions": fake_conditions,
                },
            ),
        ):
            loops = claude_widget.fetch_task_loop_status()

    self.assertEqual(len(loops), 1)
    self.assertEqual(loops[0].name, "honey-explorer")
    self.assertEqual(loops[0].model, "claude-opus-4-6")
    self.assertEqual(loops[0].effort, "high")
    self.assertEqual(loops[0].cooldown_minutes, 10)
    self.assertIsNone(loops[0].last_task_ts)
    fake_boto3.resource.assert_not_called()
```

- [ ] **Step 2: Run the test and verify RED**

Run:

```bash
python -m unittest discover -s tests -p 'test_widget_ui.py' -v
```

Expected: the new test fails because the current implementation calls `boto3.resource("dynamodb", region_name="us-east-1")`.

- [ ] **Step 3: Implement the minimal local-only reader**

Remove `CLAWD_DYNAMO_TABLE`, `CLAWD_DYNAMO_REGION`, the `boto3` imports, all scan logic, and the stale last-task calculation. Construct each enabled `TaskLoopInfo` directly from local configuration with `last_task_ts=None`. Preserve malformed/missing-file behavior and the existing row/timer interfaces.

The replacement function is:

```python
def fetch_task_loop_status() -> list[TaskLoopInfo]:
    """Read configured autonomous task loops without remote service calls."""
    try:
        with open(PROJECTS_JSON_PATH) as f:
            projects_cfg = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return []

    enabled = {
        name: cfg
        for name, cfg in projects_cfg.items()
        if cfg.get("autonomous", {}).get("enabled", False)
    }
    results: list[TaskLoopInfo] = []
    for name, cfg in enabled.items():
        auto = cfg["autonomous"]
        results.append(
            TaskLoopInfo(
                name=name,
                model=auto.get("model", "unknown"),
                effort=auto.get("effort", "—"),
                cooldown_minutes=int(auto.get("cooldown_minutes", 0)),
                last_task_ts=None,
            )
        )
    return results
```

- [ ] **Step 4: Mark the cost fix in TODO**

Add a completed TODO bullet stating that task-loop status now reads local configuration only and no longer scans DynamoDB every 60 seconds.

- [ ] **Step 5: Verify GREEN and the full suite**

Run:

```bash
python -m unittest discover -s tests -v
python -m py_compile claude_widget.py
rg -n "boto3|table\.scan|CLAWD_DYNAMO" claude_widget.py tests
```

Expected: all tests pass, compile succeeds, and the search returns no task-loop DynamoDB path.

- [ ] **Step 6: Commit**

```bash
git add claude_widget.py tests/test_widget_ui.py TODO.md
git commit -m "fix: stop Claude Indicator DynamoDB polling"
```

### Task 3: Apply S3 archive lifecycle rules

**Files:**
- No repository source files
- Operational evidence recorded in the task report

**Interfaces:**
- Consumes: existing lifecycle rules and live age/class inventory
- Produces: preserved rules plus `GLACIER` transition for overflow and day-97 `DEEP_ARCHIVE` transitions for both backups

- [ ] **Step 1: Re-verify account and lifecycle hashes**

Run `aws sts get-caller-identity`, read all three lifecycle configurations, and compare them with the preflight hashes. Stop if any lifecycle changed after preflight.

- [ ] **Step 2: Update `ubuntu-pc-overflow`**

Submit one lifecycle configuration that preserves the existing seven-day abort-incomplete-multipart rule and appends an enabled `ObjectSizeGreaterThan: 131071` rule with `Transitions: [{"Days":0,"StorageClass":"GLACIER"}]`.

Use this lifecycle payload:

```json
{
  "Rules": [
    {
      "ID": "abort-incomplete-multipart-uploads",
      "Filter": {"Prefix": ""},
      "Status": "Enabled",
      "AbortIncompleteMultipartUpload": {"DaysAfterInitiation": 7}
    },
    {
      "ID": "archive-cold-overflow-over-128k",
      "Filter": {"ObjectSizeGreaterThan": 131071},
      "Status": "Enabled",
      "Transitions": [{"Days": 0, "StorageClass": "GLACIER"}]
    }
  ]
}
```

- [ ] **Step 3: Update both backup buckets**

For each bucket, preserve the existing day-7 `GLACIER` transition and add `{"Days":97,"StorageClass":"DEEP_ARCHIVE"}` to the same enabled rule. Preserve all other rule fields verbatim.

Use this lifecycle payload for each backup bucket:

```json
{
  "Rules": [
    {
      "ID": "MoveToGlacierAfter7Days",
      "Filter": {},
      "Status": "Enabled",
      "Transitions": [
        {"Days": 7, "StorageClass": "GLACIER"},
        {"Days": 97, "StorageClass": "DEEP_ARCHIVE"}
      ]
    }
  ]
}
```

- [ ] **Step 4: Verify configuration readback**

Run `get-bucket-lifecycle-configuration` for all three and assert the preserved rule plus exact new storage classes/days. Record that physical transitions remain asynchronous.

### Task 4: Delete the two approved snapshots

**Files:**
- No repository source files
- Operational evidence recorded in the task report

**Interfaces:**
- Consumes: exact available snapshot identifiers
- Produces: absent obsolete snapshots; unchanged running production Lightsail instance

- [ ] **Step 1: Re-verify exact targets**

Confirm `FrenchProgrammingBlog-final-snapshot-20251207` and `acloudguru-manual-snap` are available, their source resources are absent, and `FrenchProgrammingBlog-New` is running.

- [ ] **Step 2: Delete exact snapshots**

Run:

```bash
aws lightsail delete-instance-snapshot --region us-east-1 --instance-snapshot-name FrenchProgrammingBlog-final-snapshot-20251207
aws rds delete-db-snapshot --region us-east-1 --db-snapshot-identifier acloudguru-manual-snap
```

- [ ] **Step 3: Verify deletion**

Poll until neither exact snapshot is returned. Re-read `FrenchProgrammingBlog-New` and require state `running`.

### Task 5: Park and retire dead domains and their Route 53 zones

**Files:**
- No repository source files
- Private DNS exports stored under `/home/sam/.codex/artifacts/aws-cost-savings-2026-07-13/`

**Interfaces:**
- Consumes: live Route 53 Domains state, existing Cloudflare account state, and three stale/retired hosted zones
- Produces: four safely parked registrations with auto-renew disabled and three hosted zones absent

- [ ] **Step 1: Export records and re-check public state**

Export the record sets for `mycoffeeexplorer.com`, `mergepdfnow.com`, and `image-ocean.com`. Confirm Coffee is already publicly delegated to Cloudflare, Merge has no public delegation, and Image Ocean remains an intentionally retired broken endpoint.

- [ ] **Step 2: Park four dead registrations on Cloudflare Free**

Using stored credentials, create empty Cloudflare Free zones for exactly
`mergepdfnow.com`, `image-ocean.com`, `pic-ocean.com`, and
`samfrenchprogramming.com`. Do not purchase a subscription and do not add
content records. For each zone, record the assigned Cloudflare nameserver pair,
change the registrar nameservers to that exact pair, require the registrar
operation to succeed, and recheck Cloudflare status plus registrar,
TLD-authoritative, and public nameservers. `mergepdfnow.com` began this step on
`clientHold`; its first nameserver operation failed while contact reachability
was pending because the existing registrant mailbox domain was unreachable.
The provisional delete-under-hold path was not used. Apply the Global
Constraints contact-recovery exception: change only the registrant `Email`
field to the already-authenticated existing Gmail profile, prove all other
contact/privacy fields unchanged by hash, and wait for the contact operation,
reachability, and hold-removal gates before one nameserver retry. Execution
passed those gates, the retry succeeded, and the normal registrar,
TLD-authoritative, public, Cloudflare, and direct-authority checks passed. Do
not delete any corresponding Route 53 zone before its applicable delegation
gate passes. `mycoffeeexplorer.com` requires no new zone because it is already
safely authoritative on Cloudflare.

- [ ] **Step 3: Disable four renewals**

Run `disable-domain-auto-renew` for exactly the four domain names in Global Constraints, then require `AutoRenew=false` from `get-domain-detail`.

- [ ] **Step 4: Delete three hosted zones**

Reconfirm that `mycoffeeexplorer.com` remains authoritative on Cloudflare and
that the applicable parking gate passed for `mergepdfnow.com` and
`image-ocean.com`. For
each of those three exact zones, delete every non-NS/SOA record in a single
Route 53 change batch, wait for `INSYNC`, then delete the hosted zone. Verify it
is absent by both ID and zone-name listing.

### Task 6: Migrate 16 active Route 53 zones to Cloudflare

**Files:**
- No repository source files
- Private pre/post record manifests stored under `/home/sam/.codex/artifacts/aws-cost-savings-2026-07-13/`

**Interfaces:**
- Consumes: Route 53 record sets, existing Cloudflare account, Route 53 Domains registrar control
- Produces: Cloudflare-authoritative DNS with matching records, a hardened source-provider overlap and resolver clean window, and no remaining Route 53 hosted zones after delayed cleanup

- [ ] **Step 1: Validate Cloudflare zone-creation authorization**

Load `CLOUDFLARE_API_TOKEN` from `~/.env` without printing it and create the first zone through `POST /client/v4/zones`. If Cloudflare returns permission denial, preserve all active AWS zones and switch to an existing authenticated dashboard/OAuth route; never request a key before exhausting stored credentials.

- [ ] **Step 2: Migrate one canary zone**

Use `imgstopdf.com` as the simple active canary without mail. Create all
non-NS/SOA records with `proxied=false`, compare manifests, update registrar
nameservers, and record when the registrar operation succeeds. Perform the
immediate Cloudflare-status, registrar/TLD/public-nameserver, full-manifest,
HTTPS, and endpoint checks, but do not delete its Route 53 zone. Keep the
unchanged source zone serving through the global and per-domain hardened
cleanup policy.

- [ ] **Step 3: Migrate the remaining zones one at a time**

Repeat the same gated sequence for these remaining active zones:

```text
myarborhub.com
rawhoneyguide.com
mushroomexplorer.com
paperworkops.com
lotsheets.com
printablespark.com
scrubpii.com
aicigarexplorer.com
christmasgiftai.com
samfrenchblog.com
squishimg.com
devtoolboxapp.com
seedgardenexplorer.com
printworkflowpacks.com
rvappliancefaultcodes.com
```

Translate Route 53 aliases in `lotsheets.com` and
`seedgardenexplorer.com` to DNS-only CNAME records and verify Cloudflare
flattening at the apex. For each domain, distinguish the immediate cutover
verification from source-zone cleanup: record the successful registrar
operation time and leave the unchanged Route 53 zone serving through the
hardened delayed-cleanup gate.

- [ ] **Step 4: Run the delayed source-zone cleanup gate**

Do not begin before the global floor `2026-07-20T15:18:57.201000Z`. For each
domain calculate `effective_not_before = max(global floor, last old-NS
observation + max(observed TTL, 172800 seconds) + 24 hours)` and move the clock
forward after any later stale answer. Starting after the effective timestamp,
run 13 rounds at five-minute intervals over one hour. Every round sends eight
UDP and one TCP NS query to each of `1.1.1.1` and `8.8.8.8`; require all
117/117 observations per resolver and domain to return only the two target
Cloudflare nameservers. Reset on any old, empty, or unexpected answer.

In rounds 1 and 13 recheck registrar nameservers, all 13 `.com` authorities,
Cloudflare active/Free/price-0 state, exact record parity, zero proxying, both
direct Cloudflare authorities, HTTPS/TLS or mail, and unchanged Route 53 source
hashes/counts. If any check fails or cannot be completed, fail closed: leave
that Route 53 zone and its records intact and do not count the migration as
cleaned up. After the clean window and both full gates pass, delete all
non-NS/SOA records, wait for `INSYNC`, delete the source hosted zone, and verify
its absence by ID and name. The original July 15 48-hour markers are historical
only; the immediate resolver pass was point-in-time evidence, not proof that
all recursive caches converged.

- [ ] **Step 5: Verify final DNS state**

Require all migrated public NS answers to be Cloudflare, representative
A/AAAA/CNAME/MX/TXT answers to match the exported intent, live HTTP endpoints
to retain their pre-change status, and Route 53 hosted-zone count to be zero
only after all delayed cleanup gates and deletions complete.

### Task 7: Review, push, restart, and measure

**Files:**
- Modify: execution evidence sections in this plan or its task reports if needed

**Interfaces:**
- Consumes: all task commits and live external state
- Produces: reviewed/pushed branch, restarted local widget, and final savings evidence

- [ ] **Step 1: Run task-level and whole-branch reviews**

Require clean spec-compliance and code-quality verdicts for each task, then a broad branch review covering all commits.

- [ ] **Step 2: Push the code branch and integrate it**

Push the reviewed branch, fast-forward `master` only after confirming origin has not advanced, then push `master`. Confirm `HEAD == origin/master`.

- [ ] **Step 3: Restart the widget**

Restart only the process whose command is `/home/sam/claude-workspace/claude-indicator/claude_widget.py`. Verify one replacement process remains running and the widget log has no startup exception.

- [ ] **Step 4: Verify DynamoDB reads stop**

Record the table read-capacity metric immediately before restart and after sufficient CloudWatch lag. Confirm the former two-scans-per-minute cadence no longer increases.

- [ ] **Step 5: Recompute savings and update memory**

Calculate verified recurring and annualized savings from resulting resources. Add one terse ad-hoc Codex memory note covering the new AWS state and updated billable-service baseline; do not edit core memory files directly.
