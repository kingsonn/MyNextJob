# Access matrix

Roles are checked on the server. A hidden button is not a control.

| Action | Admin | Adjuster | Auditor | Platform engineer |
| --- | --- | --- | --- | --- |
| Read claims | yes, masked | yes, masked | yes, masked | yes, masked |
| Unmask a field | with a reason | with a reason | no | no |
| Upload, review, publish, retire, roll back a policy | yes | no | no | no |
| Sandbox a draft | yes | no | no | no |
| Read the audit log | yes | no | yes | no |
| Read overview numbers | yes | no | no | yes |
| Approve a payout above the adjuster's authority | no | no | no | no |

Workers keep the Phase 1 tool allow-lists. The coverage worker cannot call `payments.execute_payout`. A financial action still needs the adjuster token.
