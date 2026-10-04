---
type: design-log
track: small
change: 0002-avatar-header
status: draft
---

# Avatar header

## Decisions for the implementer

- The header shows the user avatar.
- The avatar comes from the profile API.
- Each test name starts with its requirement ID.

## Problem

The profile page has no avatar. Users cannot tell accounts apart. The header needs a small image.

## Requirements

- **FR-001** (test): The header shall show the avatar.
- **FR-002** (test): When the profile API returns no avatar, the header shall show the initials.
- **FR-003** (visual): While the page is narrow, the header shall match the reference at 375px.

## Questions and answers

Q1: Does the header show the user's avatar?
A: Yes. Use the 40px avatar from the profile API.

Q2: What happens without an avatar?
A: Show the initials.
They use the first letter of each name.

## Design

The header reads the avatar URL from the profile response.
