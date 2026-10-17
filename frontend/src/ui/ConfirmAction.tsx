import { useEffect, useRef, useState } from "react";

interface ConfirmActionProps {
  label: string;
  confirmLabel: string;
  onConfirm: () => void;
  disabled?: boolean;
  busy?: boolean;
  tone?: "danger" | "primary";
  ariaLabel?: string;
}

export function ConfirmAction({
  label,
  confirmLabel,
  onConfirm,
  disabled,
  busy,
  tone = "danger",
  ariaLabel,
}: ConfirmActionProps) {
  const [armed, setArmed] = useState(false);
  const timerRef = useRef<number | undefined>(undefined);

  useEffect(() => () => {
    if (timerRef.current !== undefined) window.clearTimeout(timerRef.current);
  }, []);

  const handleClick = () => {
    if (!armed) {
      setArmed(true);
      if (timerRef.current !== undefined) window.clearTimeout(timerRef.current);
      timerRef.current = window.setTimeout(() => setArmed(false), 4000);
      return;
    }
    if (timerRef.current !== undefined) window.clearTimeout(timerRef.current);
    setArmed(false);
    onConfirm();
  };

  return (
    <button
      type="button"
      className={`btn ${armed ? "btn-danger" : tone === "danger" ? "btn-secondary" : "btn-primary"} btn-sm`}
      onClick={handleClick}
      disabled={disabled || busy}
      aria-label={ariaLabel ?? (armed ? confirmLabel : label)}
    >
      {busy ? "Working…" : armed ? confirmLabel : label}
    </button>
  );
}
