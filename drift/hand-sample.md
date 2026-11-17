# Hand sample: answer_check flags on the WorkOS docs corpus (2026-11-17)

Sample: 15 flagged calls, `random.seed(20261117)`, `random.sample(corpus.json, 15)`; list in
`hand-sample-seed20261117.json`. Each label was checked against workos-python 10.9.0 source
(commit abf30bf, `src/workos/**/_resource.py`), not against the checker's own index.

| # | call | checker | source says | verdict right | hint right |
|---|------|---------|-------------|---------------|------------|
| 1 | user_management.get_password_reset(id_=) | wrong-arg | `get_password_reset(self, id: str, *, ...)` | yes | yes |
| 2 | agents.validate_token | unknown-method | no `validate_token`; `validate_blueprint_token(agent_blueprint_id, *, agent_access_token)` | yes | yes |
| 3 | user_management.delete_user(id_=) | wrong-arg | `delete_user(self, id: str, *, ...)` | yes | yes |
| 4 | user_management.send_email_change(id_=) | wrong-arg | `send_email_change(self, id: str, *, new_email, ...)` | yes | yes |
| 5 | user_management.get_user(id_=) | wrong-arg | `get_user(self, id: str, *, ...)` | yes | yes |
| 6 | organization_domains.get_organization_domain(id_=) | wrong-arg | `get_organization_domain(self, id: str, *, ...)` | yes | yes |
| 7 | user_management.get_waitlist(id_=) | wrong-arg | `get_waitlist(self, id: str, *, ...)` | yes | yes |
| 8 | user_management.send_email_change(id_=) | wrong-arg | same as #4 | yes | yes |
| 9 | organization_domains.verify_organization_domain(id_=) | wrong-arg | `verify_organization_domain(self, id: str, *, ...)` | yes | yes |
| 10 | organizations_data_providers.update_organization_connected_account | unknown-method | no such accessor; method is on `Pipes` (`client.pipes`) | yes | first run NO (suggested `organization_domains`); fixed, now `client.pipes...` |
| 11 | user_management.get_user_identities(id_=) | wrong-arg | `get_user_identities(self, id: str, *, ...)` | yes | yes |
| 12 | directory_sync.list_users(group_id=) | wrong-arg | `list_users(self, *, ..., directory=None, group=None, ...)` | yes | yes |
| 13 | authorization.check(resource_id=) | wrong-arg | `check(self, organization_membership_id, *, permission_slug, resource_target, ...)` | yes | yes |
| 14 | user_management.create_waitlist_entry_deny(id_=) | wrong-arg | `create_waitlist_entry_deny(self, id: str, *, ...)` | yes | yes |
| 15 | user_management.create_waitlist_entry_approve(id_=) | wrong-arg | `create_waitlist_entry_approve(self, id: str, *, ...)` | yes | yes |

Result: verdicts 15/15 right (0 false flags in sample). Hints 14/15 on first run; the miss led to two
tested fixes in check.py (point to the resource that has the method; no fuzzy accessor guess when no
resource has it). Rerun after the fix: corpus counts unchanged.

Not measured here: misses (calls the checker passes that are wrong). The seeded bot eval covers that.
