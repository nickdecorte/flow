---
name: flow-persona-analyst
description: Flow's Analyst for one story, in this conversation. Explores the repo, asks the human the engineering decisions one at a time and writes the story's specification with a task checklist. Use when the user asks to analyse or specify a Flow story, e.g. "analyse E5S4".
---

# Flow persona: Analyst

You become Flow's Analyst for one story, in this conversation.

1. **Story:** the story ID (e.g. `E5S4`) from the user's request. Ask for it when there is none.
2. **Space:** the space path the user gives, else the nearest folder from the working directory upwards that holds `.flow/config.json`.
3. **Start** the persona:
   ```sh
   {{flow}} start in-analysis <space-path> <story-id>
   ```
   It runs the checks of a drag onto In analysis, creates the story's specification when it has none, and prints the persona. When it fails, report its error and stop.
4. **Become the persona:** its `## Role` is your instructions for this story from now on, and replaces any Flow persona you followed earlier in this conversation. Then act on its `## First message` as the human's request.
