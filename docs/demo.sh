#!/usr/bin/env bash
# Stylized, honest terminal demo of the MAP golden path.
# Rendered to docs/demo.gif via docs/demo.tape (vhs). Not a live agent capture —
# it shows the real command sequence, real artifact names, and real stage
# semantics, with illustrative task content. Re-render: `vhs docs/demo.tape`.
set -u

# ---- palette ----
C_PROMPT='\033[38;5;81m'   # cyan prompt
C_CMD='\033[1m\033[97m'    # bold white command
C_DIM='\033[38;5;245m'     # dim description
C_OK='\033[38;5;114m'      # green
C_PLAN='\033[38;5;213m'    # pink
C_BUILD='\033[38;5;215m'   # orange
C_CHECK='\033[38;5;81m'    # cyan
C_REVIEW='\033[38;5;141m'  # purple
C_LEARN='\033[38;5;114m'   # green
C_PAUSE='\033[38;5;221m'   # yellow
R='\033[0m'

type_cmd() {  # animate typing a slash-command after a prompt
  printf "${C_PROMPT}▸ ${R}"
  local s="$1" i
  for (( i=0; i<${#s}; i++ )); do printf "${C_CMD}%s${R}" "${s:$i:1}"; sleep 0.028; done
  printf '\n'; sleep 0.35
}
line() { printf "%b\n" "$1"; sleep 0.22; }
gap()  { printf '\n'; sleep 0.30; }

clear
sleep 0.4
line "${C_DIM}# install once, then drive the loop from Claude Code${R}"
printf "${C_PROMPT}\$ ${R}${C_CMD}mapify init${R}\n"; sleep 0.5
line "  ${C_OK}✓${R} MAP installed → ${C_DIM}.claude/ skills + .map/ workflow${R}"
gap
printf "${C_PROMPT}\$ ${R}${C_CMD}claude${R}\n"; sleep 0.5
line "  ${C_DIM}Claude Code — MAP Framework ready${R}"
gap

type_cmd '/map-plan  add rate limiting to the public API'
line "  ${C_PLAN}PLAN${R}   ${C_DIM}clarify behavior · decompose into reviewable subtasks${R}"
line "         ${C_DIM}→${R} spec_main.md  ${C_DIM}·${R}  blueprint.json ${C_DIM}(size- & concern-checked)${R}"
line "  ${C_PAUSE}⏸${R}  ${C_DIM}you approve the plan before any code is written${R}"
gap

type_cmd '/map-efficient'
line "  ${C_BUILD}BUILD${R}  ${C_DIM}implement the approved plan, subtask by subtask${R}"
line "         ST-001 ${C_OK}✓${R}   ST-002 ${C_OK}✓${R}   ST-003 ${C_OK}✓${R}   ST-004 ${C_OK}✓${R}"
gap

type_cmd '/map-check'
line "  ${C_CHECK}CHECK${R}  ${C_DIM}quality gates run against the plan — pass${R}"
gap

type_cmd '/map-review'
line "  ${C_REVIEW}REVIEW${R} ${C_DIM}semantic review vs spec, tests & diff${R}"
line "         ${C_DIM}→${R} .map/<branch>/review-bundle.json"
gap

type_cmd '/map-learn'
line "  ${C_LEARN}LEARN${R}  ${C_DIM}gotchas saved as project memory for next session${R}"
gap
sleep 0.4
line "  ${C_DIM}idea → prompt → code → hope${R}                 ${C_DIM}✗ without MAP${R}"
line "  ${C_OK}SPEC → PLAN → TEST → CODE → REVIEW → LEARN${R}   ${C_OK}✓ with MAP${R}"
sleep 1.4
