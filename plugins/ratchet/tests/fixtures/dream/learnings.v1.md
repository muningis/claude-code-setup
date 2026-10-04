# Learnings (human feedback as rules)

- Every native screen must respect platform safe-area insets (status bar / notch / home indicator); content must never render under system UI. (cp5, 2026-10-02)
- Anything the web animates to show time passing (shrinking bars, countdowns) must visibly progress natively too; a static timer reads as a frozen app. (cp7 human gate, 2026-10-03)
- Every native text field must be dismissible: the keyboard return/Done key ends editing, and tapping outside the field clears focus too. (ios-settings-themes cp2 human gate, 2026-10-03)
