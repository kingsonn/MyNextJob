### Phase 4: Safety and admin console (weeks 13 to 15)

- [x] Implement input, context, planning, tool and output guardrails
- [x] Add PII masking with reversible tokenisation and log redaction
- [x] Build the red-team dataset and benign look-alike set
- [x] Run the suite, record block and false-positive rates by attack class
- [x] Write the audit log, access matrix, threat model and incident runbooks

**Added scope for the admin console (adds about one week):**

- [x] Implement roles and server-side permission checks for every admin route
- [x] Build the claims explorer and claim detail page with trace and citation links
- [x] Build the policies and documents page: upload, ingestion progress, review screen, publish, retire, rollback
- [x] Build the policy sandbox for testing a draft version before publishing
- [x] Build the audit log viewer and the overview numbers page
- [x] Harden uploads (file-type check, limits, malware scan) and add the hostile-upload tests