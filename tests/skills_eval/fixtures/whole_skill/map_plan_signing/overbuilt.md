# Candidate signing plan

## Decisions Made

Add a publish-and-sign wrapper, use it for both publishing jobs and keep the existing release job.

## Acceptance Criteria

- AC-1. Each publishing job calls the new wrapper.
- AC-2. Each caller checks signer availability before invoking the wrapper.
- AC-3. Require a pinned checksum before installing the signing tool.
- AC-4. Look up the digest again after signing and fail if the tag moved.
- AC-5. Add a verification CLI with its own test suite.

## Blueprint excerpt

| Subtask | Coverage | Validation criteria |
| --- | --- | --- |
| Connect both publishers | AC-1, AC-2 | Exercise the wrapper and the tool checks for both jobs. Set an alternate `REGISTRY` and assert that the image cannot be published there. |
| Update signing | AC-3, AC-4 | Refuse an unpinned installer and fail on a changed tag. |
| Build the verifier | AC-5 | Run the new CLI's tests. |
