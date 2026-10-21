# PerClip Repository Instructions

## Required Context

- Read `HANDOFF.md` before planning or changing the project.
- Read the relevant contracts, recent `Records.md` entries, code, tests, and
  verification evidence linked from the handoff. Do not rely on README or an
  old roadmap section alone.
- Distinguish existing verified behavior from user-approved future behavior.

## Mandatory Handoff Update

Update `HANDOFF.md` in the same change whenever work changes product decisions,
terminology, flows, architecture, data/API contracts, implementation status,
active branches, merge/deployment state, verification evidence, known gaps, or
the recommended next-stage plan.

Pure typo or formatting-only changes do not require a handoff update.
`Records.md` remains the detailed append-only delivery log; update it for stage
or delivery work and keep `HANDOFF.md` as the concise current snapshot. Never
put secrets, private content, credentials, or sensitive infrastructure details
in either file.

## Execution

- Preserve established structure and make the narrowest useful change.
- Use a dedicated worktree/branch for new implementation stages unless the user
  explicitly chooses otherwise.
- Run Android emulator verification unobtrusively in the background by default,
  using explicit `adb` device serials and captured evidence. Open `scrcpy` or an
  emulator window when the user asks to watch the device; if background evidence
  is insufficient, explain why visible inspection is needed before opening it.
- Complete work within the authorized scope; existing authorization remains valid
  for that scope and does not need repeated confirmation.
- Do not merge, deploy, publish, submit, or use real external services without
  explicit authorization. Prepare and verify the concrete result before requesting
  any missing authorization.
- Verify proportionally to risk and report exactly what was and was not
  verified.
