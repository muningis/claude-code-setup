# Learnings

Human notes live above the entries and must stay byte for byte.

### L-001
- scope: mobile/**
- rule: Check each text field with the keyboard open, on a device or a simulator.
- check: The device check pack lists each new text field.
- source: cp5 4-human.md
- origin: human
- helpful: 0 · harmful: 0 · status: active

### L-002
- scope: server/**
- rule: Log the request ID on every error path of a handler.
- check: Each catch block of a handler logs the request ID.
- source: cp2 4-human.md
- origin: human
- helpful: 0 · harmful: 0 · status: active

### L-003
- scope: mobile/**/*.kt
- rule: Keep the screen on a transient disconnect and show a reconnecting banner.
- check: A test drives a disconnect and expects the same screen.
- source: cp7 4-human.md
- origin: human
- helpful: 0 · harmful: 0 · status: active

### L-004
- scope: docs/**
- rule: State each requirement with one verb in the present tense.
- check: The doc linter finds no sentence with two verbs.
- source: cp3 decisions.md
- origin: human
- helpful: 0 · harmful: 0 · status: active

## Notes
Free text after the entries. It must survive too.
