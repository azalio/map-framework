---
paths:
  - "**/*.go"
---

# Implementation Patterns (Learned)

<!-- MAP-LEARN: populated by /map-learn. Edit freely, commit with project. -->

- **Re-fetch after update** (2026-03-15): When calling r.Update() on a Kubernetes resource, always re-fetch with r.Get() before reading updated fields because the in-memory object is stale after update. [workflow: map-efficient]

- **SetStatusCondition needs observedGeneration** (2026-03-16): When using meta.SetStatusCondition(), always set ObservedGeneration to the resource's current Generation to prevent stale condition reporting. [workflow: map-debug]
  ```go
  meta.SetStatusCondition(&obj.Status.Conditions, metav1.Condition{
      ObservedGeneration: obj.Generation, // required
  })
  ```

- **Webhook latency** (2026-03-18): When implementing admission webhooks, always read from status/cache instead of listing pods or querying external APIs because webhook timeout is 10s and slow webhooks block all API operations. [workflow: map-efficient]
