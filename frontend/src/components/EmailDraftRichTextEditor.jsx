import { useEditor, EditorContent } from "@tiptap/react";
import StarterKit from "@tiptap/starter-kit";
import { Bold, Heading2, Italic, List, ListOrdered, Quote, Redo2, Strikethrough, Undo2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { normalizeDraftBodyForEditor } from "@/lib/emailDraftBody";
import { t } from "@/lib/i18n";

function ToolbarButton({ onClick, active, disabled, children, title }) {
  return (
    <Button
      type="button"
      size="sm"
      variant={active ? "secondary" : "ghost"}
      className="h-8 w-8 shrink-0 p-0"
      onMouseDown={(e) => e.preventDefault()}
      onClick={onClick}
      disabled={disabled}
      title={title}
    >
      {children}
    </Button>
  );
}

export function EmailDraftRichTextEditor({ initialBody, onChange, className }) {
  const editor = useEditor({
    extensions: [StarterKit],
    content: normalizeDraftBodyForEditor(initialBody),
    editorProps: {
      attributes: {
        class: cn(
          "tiptap-editor min-h-[220px] w-full px-3 py-2 text-sm outline-none",
          "focus-visible:outline-none",
          "[&_span[data-variable]]:bg-primary/20 [&_span[data-variable]]:text-primary [&_span[data-variable]]:px-1 [&_span[data-variable]]:rounded [&_span[data-variable]]:font-mono"
        ),
      },
    },
    onUpdate: ({ editor: ed }) => {
      onChange(ed.getHTML());
    },
  });

  if (!editor) {
    return <div className="min-h-[260px] rounded-md border border-input bg-muted/20" aria-hidden />;
  }

  return (
    <div className={cn("space-y-2", className)}>
      <div className="flex flex-wrap gap-0.5 rounded-md border border-input bg-muted/30 p-1" role="toolbar" aria-label={t("Text formatting")}>
        <ToolbarButton
          title={t("Bold")}
          active={editor.isActive("bold")}
          onClick={() => editor.chain().focus().toggleBold().run()}
        >
          <Bold className="h-4 w-4" />
        </ToolbarButton>
        <ToolbarButton
          title={t("Italic")}
          active={editor.isActive("italic")}
          onClick={() => editor.chain().focus().toggleItalic().run()}
        >
          <Italic className="h-4 w-4" />
        </ToolbarButton>
        <ToolbarButton
          title={t("Strikethrough")}
          active={editor.isActive("strike")}
          onClick={() => editor.chain().focus().toggleStrike().run()}
        >
          <Strikethrough className="h-4 w-4" />
        </ToolbarButton>
        <ToolbarButton
          title={t("Heading")}
          active={editor.isActive("heading", { level: 2 })}
          onClick={() => editor.chain().focus().toggleHeading({ level: 2 }).run()}
        >
          <Heading2 className="h-4 w-4" />
        </ToolbarButton>
        <ToolbarButton
          title={t("Bullet list")}
          active={editor.isActive("bulletList")}
          onClick={() => editor.chain().focus().toggleBulletList().run()}
        >
          <List className="h-4 w-4" />
        </ToolbarButton>
        <ToolbarButton
          title={t("Numbered list")}
          active={editor.isActive("orderedList")}
          onClick={() => editor.chain().focus().toggleOrderedList().run()}
        >
          <ListOrdered className="h-4 w-4" />
        </ToolbarButton>
        <ToolbarButton
          title={t("Quote")}
          active={editor.isActive("blockquote")}
          onClick={() => editor.chain().focus().toggleBlockquote().run()}
        >
          <Quote className="h-4 w-4" />
        </ToolbarButton>
        <ToolbarButton title={t("Undo")} onClick={() => editor.chain().focus().undo().run()}>
          <Undo2 className="h-4 w-4" />
        </ToolbarButton>
        <ToolbarButton title={t("Redo")} onClick={() => editor.chain().focus().redo().run()}>
          <Redo2 className="h-4 w-4" />
        </ToolbarButton>
      </div>
      <div className="rounded-md border border-input bg-background ring-offset-background focus-within:ring-2 focus-within:ring-ring focus-within:ring-offset-2">
        <EditorContent editor={editor} />
      </div>
    </div>
  );
}
