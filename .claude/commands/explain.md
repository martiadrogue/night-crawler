---
description: Explain a specific part, module, or feature of this application in plain context.
---

Analyze the section or feature of the application specified by the user ($ARGUMENTS$). If no specific area was provided, identify the primary core module of the application and analyze that.

Please break down your explanation into the following sections:

1. **High-Level Purpose** (1-2 sentences): What business logic or user need does this specific component handle?
2. **Key Files & Entry Points**: List the primary files, components, or entry points involved, with a brief sentence on what each file's responsibility is.
3. **Data Flow & Execution Path**: Walk through a step-by-step trace of how data or execution flows through this part of the app (e.g., Request/Action -> Controller/Handler -> Service/State -> DB/Render).
4. **Dependencies & Interactions**: What other parts of the app does this section rely on or communicate with?
5. **Gotchas or Non-Obvious Patterns**: Point out any non-standard architectural choices, tricky state management, edge cases, or side effects to watch out for.

Be direct, practical, and link explanations back to exact file paths where relevant.
