// A list of short words typed one at a time: Enter or comma adds, × removes.
import { useState } from "react";

type Props = {
  value: string[];
  onChange: (v: string[]) => void;
  placeholder?: string;
  max?: number;
};

export default function TagInput({ value, onChange, placeholder, max = 30 }: Props) {
  const [text, setText] = useState("");

  function add(raw: string) {
    const parts = raw.split(",").map((s) => s.trim()).filter(Boolean);
    const next = [...value];
    for (const p of parts) if (!next.includes(p) && next.length < max) next.push(p);
    onChange(next);
    setText("");
  }

  return (
    <div className="input flex flex-wrap items-center gap-1.5">
      {value.map((tag) => (
        <span key={tag} className="inline-flex items-center gap-1 rounded bg-indigo-50 px-2 py-0.5 text-xs text-indigo-800">
          {tag}
          <button
            type="button"
            aria-label={`remove ${tag}`}
            className="text-indigo-500 hover:text-indigo-900"
            onClick={() => onChange(value.filter((t) => t !== tag))}
          >
            ×
          </button>
        </span>
      ))}
      <input
        className="min-w-32 flex-1 border-0 p-0 text-sm focus:outline-none"
        value={text}
        placeholder={value.length >= max ? `at most ${max}` : placeholder}
        disabled={value.length >= max}
        onChange={(e) => (e.target.value.includes(",") ? add(e.target.value) : setText(e.target.value))}
        onKeyDown={(e) => {
          if (e.key === "Enter") {
            e.preventDefault();
            if (text.trim()) add(text);
          } else if (e.key === "Backspace" && !text && value.length) {
            onChange(value.slice(0, -1));
          }
        }}
        onBlur={() => text.trim() && add(text)}
      />
    </div>
  );
}
