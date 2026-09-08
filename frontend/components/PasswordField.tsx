import { useId, useState } from "react";
// A password box people can read back. The toggle is a real button rather than
// something inside the <label>, because a click on a label is forwarded to the
// control it names — nesting it would put the caret in the field instead of
// revealing the text.
export default function PasswordField({
  label,
  value,
  onChange,
  autoComplete,
  minLength,
  hint,
  problem,
  name,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  autoComplete: "new-password" | "current-password";
  minLength?: number;
  hint?: string;
  problem?: string;
  name?: string;
}) {
  const [shown, setShown] = useState(false);
  const id = useId();
  const hintId = `${id}-hint`;
  const problemId = `${id}-problem`;
  const describedBy =
    [hint ? hintId : null, problem ? problemId : null]
      .filter(Boolean)
      .join(" ") || undefined;
  return (
    <div className="field">
      <label htmlFor={id}>{label}</label>
      <div className="password-input">
        <input
          id={id}
          name={name}
          type={shown ? "text" : "password"}
          autoComplete={autoComplete}
          minLength={minLength}
          maxLength={128}
          required
          value={value}
          onChange={(e) => onChange(e.target.value)}
          aria-describedby={describedBy}
          aria-invalid={problem ? true : undefined}
        />
        <button
          type="button"
          className="password-toggle"
          onClick={() => setShown((was) => !was)}
          aria-pressed={shown}
          // Two password boxes can share a form, so the name says which one.
          aria-label={`${shown ? "Hide" : "Show"} ${label.toLowerCase()}`}
        >
          {shown ? "Hide" : "Show"}
        </button>
      </div>
      {hint && <small id={hintId}>{hint}</small>}
      {problem && (
        <small id={problemId} className="field-problem" role="alert">
          {problem}
        </small>
      )}
    </div>
  );
}
