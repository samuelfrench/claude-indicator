---
title: "Authorized beta recruiting replies: existing-session access"
status: waiting-sam
area: product
due: null
updated: 2026-10-08
owner: sam
brief: "Posting is authorized within caps, but existing Chrome X/Reddit sessions are signed out; no replies sent. Saved r/codex queue also forbids bots."
refs: ["docs/todo/done/product/beta-phase-1.md"]
test: null
---
- **What:** Execute only Sam’s newly authorized public beta-recruiting replies, with private per-reply logs and signup/feedback tracking. Original beta preparation is already complete; a launch or paid release is not authorized.
- **Authority:** Latest direct user instruction reinstates the goal file’s CHANGED permission and supersedes prior drafts-only checkpoints. No repeated approval is needed for qualifying replies. Only usage-limit/reset threads under Sam’s existing accounts; no DMs, top-level posts, likes/follows, new accounts, passwords, cookie/token import or CAPTCHA/2FA bypass. At most 5 replies per platform per day and 30 campaign total; every reply discloses “I built this”, uses varied truthful copy, follows current community rules. Stop immediately on missing login, removal, flag, warning or rate limit.
- **Observed blocker:** 2026-10-08 01:31 CT live existing Chrome extension X session showed “Log in or sign up for X” and “Log in with username or email”. No credentials entered or reply attempted. This is a concrete signed-out session, not a generic unavailable-browser fault. The candidate remains open as a Chrome handoff; its URL and tab identity are in the private access receipt.
- **Reddit:** Live Chrome `https://www.reddit.com/r/codex/` showed Sign Up/Log In and rule 9 “Don’t use bots. Read up on BotBouncer”. All 20 saved Reddit rows are in that community and cannot be posted automatically under the obey-rules guardrail. Public JSON supported the restriction but was cache-labelled two weeks old; current browser UI is the fresh evidence. Do not evade bot moderation or substitute a different identity. Other communities need their own current qualifying threads/rules.
- **Next [Sam-only]:** Sign into the existing X account in the retained Chrome candidate tab. Do not give credentials to Codex. Once its normal page is signed in, root verifies the correct account and resumes permitted replies without another approval question. Reddit login alone would not make r/codex automation eligible.
- **Resume:** Reread `/home/sam/indicator-beta-codex-goal.txt`, check `~/.cache/indicator-beta/STOP`, then read `~/indicator-beta/recruit-posts.md`, `recruit-posting-access-check.json` and drafts. Recheck account, current thread/context, exact “I built this” disclosure, platform length, duplicates and day/campaign counts. Verify actual submitted reply URL/text and absence of warnings before logging and proceeding one reply at a time. Do not retry an uncertain submission without proving whether it posted. Stop at today’s cap; do not create a scheduler without separate instruction.
- **Tracking/result:** Fresh all-state GitHub issue query returned 0 issues; `~/indicator-beta/recruits.md` has 0 confirmed users/feedback/provider requests. Logged campaign/today total 0 posts. Candidate handles, per-account identity details and posting receipts remain private.
- **External clocks:** Daily cap resets by logged Central date. Account sign-in is required under Sam’s existing-session restriction. Actual user signups/feedback are future observations; drafts/account access do not prove recruitment. No new billing.
- **Done:** The authorized campaign has verified posted replies within its caps, each logged with platform/reply URL/thread URL/date/text, and the signup/feedback tracker is refreshed. Until then, retain concrete access/rule/stop conditions as blockers. Broader 10–20 users/launch/paid success remain separate.
