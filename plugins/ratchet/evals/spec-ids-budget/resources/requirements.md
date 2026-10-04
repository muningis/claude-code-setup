# Requirements

The module is `src/slug.js`. It exports `slugify(text)`.

- **FR-001** (test): When the text has spaces, the slugify function shall replace each run of spaces with one dash.
- **FR-002** (test): If the text is empty, then the slugify function shall return an empty string.
- **FR-003** (device): While the phone is offline, the editor shall show the slug of the title.
