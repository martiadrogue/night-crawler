---
description: create a commit message by analazying git diff
allowed-tools: Bash(git status:*), Bash(git diff --staged), Bash(git commit:*)
---

## Context

- Current git status: !`git status`
- Current git diff:  !`git diff -staged` 

## Your task:

Analize avobe staged git changes and create a commit message. Use present tense and explain "why" something had changed, not hust "what"

## Commit types with emogies:

only use the following emogies

 - feat: `feat:` - new feature
 - fix: `fix:` - bug fix
 - refactor: `refactor:` - refactoring code
 - docs: `docs:` - documentation
 - style: `style:` - styling/formatting
 - test: `test:` - tests
 - pref: `feat:` - performance  

## Format:

use following format for making the commit message

<emogi> <type>: <concise_description>
<optional_body_explainig_why>

## Output:

1. show summary of changes currently staged
2. propose commit message with appropiate emoji
3. ask for confirmation before commiting

DO NOT auto-commit - wait for the user approval, and only commit if the user say so

