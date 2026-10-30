import {
  RichTextKit,
  Paragraph,
  HeadingGroup,
  Separator,
  Bold,
  Italic,
  BulletList,
  OrderedList,
  AlignLeft,
  AlignCenter,
  AlignRight,
  FontColor,
  InsertImage,
  InsertVideo,
  InsertLink,
  Blockquote,
  InlineCode,
  HorizontalRule,
  InsertTable,
  type MenuItem,
} from 'frappe-ui/editor'
import { useFileUpload } from 'frappe-ui'
import type { Extension } from '@tiptap/core'
import type { MaybeRefOrGetter } from 'vue'

/** A mentionable user as the editor expects it. `id` is the email — `extract_mentions`
 *  (crm/api/comment.py) reads it back off `data-id`. */
export interface MentionItem {
  id: string
  label: string
}

/**
 * Extension list for a CRM rich-text editor.
 *
 * Pass `mentions` as a getter, not a snapshot — the `@` list then stays in sync
 * as users load.
 */
export function buildEditorExtensions(
  options: {
    mentions?: MaybeRefOrGetter<MentionItem[]>
    starterKit?: Record<string, unknown>
    extra?: Extension[]
  } = {},
): Extension[] {
  return [
    RichTextKit.configure({
      heading: { levels: [2, 3, 4, 5, 6] },
      ...(options.mentions ? { mention: { items: options.mentions } } : {}),
      ...(options.starterKit ? { starterKit: options.starterKit } : {}),
    }),
    ...(options.extra ?? []),
  ]
}

/** Composer toolbar — ports the v0 `textEditorMenuButtons`. In-table operations
 *  now live in the contextual `EditorTableMenu` instead of a toolbar dropdown. */
export const fullToolbar: MenuItem[] = [
  Paragraph,
  HeadingGroup,
  Separator,
  Bold,
  Italic,
  Separator,
  BulletList,
  OrderedList,
  Separator,
  AlignLeft,
  AlignCenter,
  AlignRight,
  FontColor,
  Separator,
  InsertImage,
  InsertVideo,
  InsertLink,
  Blockquote,
  InlineCode,
  HorizontalRule,
  InsertTable,
]

/** Upload handler for images/files dropped or pasted into an editor. */
export function uploadFile(
  file: File,
  doctype?: string,
  docname?: string,
  isPrivate = true,
) {
  return useFileUpload().upload(file, {
    private: isPrivate,
    doctype,
    docname,
  })
}

/**
 * Upload handler for the email composer.
 *
 * An image placed in an email is fetched by the recipient's mail client,
 * which has no session: a private file is a 403, so the customer saw a broken
 * image. The upload is public instead, under a random prefix, so its address
 * is known only to the people the email went to rather than to anyone who
 * guesses `/files/image.png`.
 */
export function uploadEmailFile(
  file: File,
  doctype?: string,
  docname?: string,
) {
  const token = Array.from(crypto.getRandomValues(new Uint8Array(12)), (b) =>
    b.toString(16).padStart(2, '0'),
  ).join('')
  const unguessable = new File([file], `${token}-${file.name}`, {
    type: file.type,
  })
  return uploadFile(unguessable, doctype, docname, false)
}
