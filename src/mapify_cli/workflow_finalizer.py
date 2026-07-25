"""
Workflow Finalization Logic for MAP Framework

Handles early termination of workflows, transitioning incomplete subtasks
to won't_do status when a workflow is abandoned before completion.

Part of ST-006: Create finalize_workflow() function for won't_do transition.
"""


from mapify_cli.workflow_state import WorkflowState


def finalize_workflow(
    state: WorkflowState, reason: str, by_user: bool = True
) -> WorkflowState:
    """
    Finalize a workflow by marking incomplete subtasks as won't_do.

    This function is called when a workflow is intentionally abandoned before
    completion (e.g., user cancellation, requirements changed, blocking issues).
    It preserves completed and failed subtask statuses while transitioning all
    pending and in_progress subtasks to won't_do status.

    Args:
        state: Current workflow state to finalize
        reason: Explanation for why the workflow is ending early
        by_user: Whether termination was user-initiated (default True)

    Returns:
        Updated workflow state with won't_do transitions applied

    Postconditions:
        - All subtasks with status 'pending' or 'in_progress' → status 'won't_do'
        - Subtasks with status 'complete' or 'failed' → status unchanged
        - state.current_phase → WorkflowPhase.WONT_DO
        - state.ended_early populated with reason and active subtask
    """
    # Find the currently active subtask (in_progress)
    # Use None instead of empty string to match schema expectations
    active_subtask_id: str | None = None
    for subtask in state.subtasks:
        if subtask.status == "in_progress":
            active_subtask_id = subtask.id
            break

    # Transition all incomplete subtasks to won't_do
    for subtask in state.subtasks:
        if subtask.status in ("pending", "in_progress"):
            subtask.status = "won't_do"

    # Mark workflow as ended early (sets terminal_status and phase)
    state.mark_ended_early(reason=reason, subtask_id=active_subtask_id, by_user=by_user)

    return state
