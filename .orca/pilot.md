# Orca pilot policy

Validated runtime baseline:

* Orca executable: `/Applications/Orca.app/Contents/Resources/bin/orca`
* Orca: `1.4.216`
* Codex: `0.156.1` (pinned during the pilot)

Model roles:

* Coordinator: `gpt-5.6-sol` / `medium`
* STANDARD specification workers: `gpt-5.6-luna` / `xhigh`
* QUICK, STANDARD and COMPLEX implementation/fix workers: `gpt-5.6-luna` / `xhigh`
* COMPLEX planning/design workers: `gpt-5.6-sol` / `medium`
* Independent reviewers: `gpt-5.6-luna` / `max`

Do not change runtime versions or model roles during the pilot unless the user explicitly requests it.

