# Open questions for the Slite API team

Context: `slite-io` mirrors Markdown/MDX files from Git into Slite notes. We
create and update notes through `POST /notes` and `PUT /notes/{noteId}`, using
either the `markdown` or `sliteml` content field. The following behaviors are
unclear from the public API documentation and are currently blockers for a
reliable mirror.

## 1. In-document heading links are lost when updating a note

On first creation, Markdown heading links are converted correctly. On update,
the same Markdown produces a different result and the links are lost.

Observed sequence:

1. `POST /notes` with Markdown containing:

   ```markdown
   [Mermaid](#mermaid)
   ```

   The rendered note has a working in-document link. Reading the note back with
   `GET /notes/{noteId}?format=sliteml&compact=true` returns:

   ```text
   <a url="#mermaid">Mermaid</a>
   ```

2. `PUT /notes/{noteId}` with the same Markdown body and the same title.
3. The link no longer works, or the note’s link content is different from the
   create result.


## 2. How to create links from Slite path

Via the API, we can transfer the folder structure and place notes where we want them.

It would be great to be able to link them. Usually, we upload a bunch of notes that
live next to each other, and have relative links like `../../parent/neighbouring_note`

Currently, we did not find a sliteml component to create a `<note-link>` based on a
relative path. Clearly, a neighbouring notes id is not none, nor inferable before upload.
(I guess we could build a two-step pipeline and resolve relative links to ids, but that
seems like a rather involved workaround).


## 3. Uploading images referenced by relative paths

Source Markdown contains images relative to the Markdown file, for example:

```markdown
![Architecture](./assets/architecture.png)
```

We have the image as a local file and need to upload it with the note.

Questions:

- Is there a public API endpoint for uploading image or file assets? We only see
  note, tile, and content endpoints in the public reference.

* For a mirror, how can we map a source-relative image path to the uploaded
  Slite asset without storing state outside the note?

## 4. Frontmatter and custom metadata in SliteML

We would like to carry source metadata such as source path, repository, commit,
last source change, and last sync time.

Does SliteML support YAML frontmatter? If so, which fields are recognized and persisted?

## 5. Locking mirrored notes so edits only happen through the API

In our case, these notes are read-only mirrors. Users should read them in Slite, but edit the
source Markdown in Git and open a pull request. We need to prevent accidental
edits in Slite.

The editor exposes “protect editing”, but we found no public API endpoint for
note permissions or protection.

Questions:

- Is there a way to enable “protect editing” or an equivalent read-only state
  through the public API?
- Or is there a note-level `locked`, `readOnly`, or permission field on
  create/update?

## 6. Creating and preserving interactive user mentions

Writing `@user` in the Slite editor creates an interactive mention. Reading the
note back as SliteML shows markup similar to:

```text
<mention user-id="USER_ID" name="Display Name">@Display Name</mention>
```

Exporting the note to Markdown and re-importing it loses the interactive user
connection.
