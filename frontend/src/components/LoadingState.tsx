import { LoaderCircle } from "lucide-react";

interface LoadingStateProps {
  message?: string;
  size?: "small" | "medium" | "large";
}

export function LoadingState({ message = "Loading...", size = "medium" }: LoadingStateProps) {
  const sizeClasses = {
    small: "size-4",
    medium: "size-6",
    large: "size-8"
  };

  return (
    <div className="flex flex-col items-center justify-center gap-3 p-8 text-center">
      <LoaderCircle className={`${sizeClasses[size]} text-[var(--color-primary-blue)] animate-spin`} />
      {message && <p className="text-sm text-[var(--color-text-secondary)]">{message}</p>}
    </div>
  );
}
