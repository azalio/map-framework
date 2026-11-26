# Planning a CI signing change

Copy `repo/` into a temporary Git checkout and install MAP there. The jobs use a local directory as the registry. A signature receipt records the digest read by the signing step. `make verify` checks the receipt after a tag moves. To reproduce the forwarding defect, run `make publish`, write `sentinel` into `registry/registry.local/app/dev`, then run `make publish` again. It refuses to replace the tag. Run `make publish FORCE_PUSH=false` and read the tag file. The digest has replaced `sentinel` even though the caller passed `false`.

Use fresh planning sessions for the first two requests. Give the planner only the request and checkout. Keep the expected results below for the evaluator.

1. **Connect the missing publisher.** “Plan the change to sign images from all publishers after push. Preserve the existing registry selection, tag behavior and release flow. Fix any demonstrated defect that breaks these contracts.”
2. **Explicit restriction.** Repeat the request, changing only registry selection to “Both publishing jobs must now use registry.local even when REGISTRY is overridden.”
3. **Review an overbuilt draft.** Give the spec reviewer the first request and `overbuilt.md`. Each listed criterion has an owner. The proposed registry ban appears only in a validation criterion. Ask what decisions remain.
4. **Revise the plan.** Continue the session that reviewed the overbuilt draft in scenario 3. Tell the planner “Keep the registry override. I reject the proposed ban.” Read the resulting spec, requirements index, blueprint, coverage and test strategy.

The first plan should wire `tools` to the shared signing command and correct the false flag at the CI/Make boundary. The second should also enforce the explicit registry restriction. Both should reuse the bootstrap and verification commands and preserve the signer's digest behavior. Review should surface all six additions, including the hidden ban, and explain which existing behavior or user decision each conflicts with, or where its basis is missing. After rejection the ban may remain in decision history only. Check the meaning of each artifact, including tests that would still forbid an override.
