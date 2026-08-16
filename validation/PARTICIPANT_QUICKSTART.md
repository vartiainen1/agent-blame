# agent-blame — Participant Quick Start

Welcome! You are evaluating a developer tool called **agent-blame**. Thank
you for your time — your honest feedback is the whole point.

## What agent-blame is

agent-blame investigates **git history**. Where `git blame` tells you who
last touched a line, agent-blame tries to answer bigger questions:

- Why does this code exist, and where did it come from?
- Was it moved here from somewhere else?
- Who calls it?
- Has it been reverted or fixed before?
- What should I know before changing it?

It reads only your local repository. It runs no code, sends nothing over
the network, and makes no changes.

## Install and run

On the study machine, agent-blame is already installed. To check:

```bash
agent-blame --help
agent-blame --version
```

If the `agent-blame` command is not found, the no-install way works too
(ask the facilitator, or):

```bash
# Windows (Git Bash)
PYTHONPATH=/path/to/agent-blame python -m agent_blame --help
# macOS/Linux
PYTHONPATH=/path/to/agent-blame python3 -m agent_blame --help
```

Use it **from inside the repository** you are investigating (any
subdirectory works).

## Your task

The facilitator has given you a task sheet (`TASK_SHEET.md`) with one
scenario. Work through it as you normally would. Some notes:

- You may use `agent-blame` however you like.
- You may also use normal `git` commands if you want — that is fine and is
  part of what we are comparing.
- There is no "correct" command sequence and no expected answer you need to
  find. We are measuring what the tool naturally does for you.
- If something is confusing, that is a finding, not a failure.

## Feedback

When you finish (or feel you have gone as far as you can), tell the
facilitator. They will ask you a few questions about what you found and
what you would have done without the tool. There are no wrong answers.

If anything breaks or produces something you distrust, say so — that is
exactly what the study is for.

Thank you!
