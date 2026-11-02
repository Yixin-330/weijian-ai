import { type ReactNode, type CSSProperties } from "react";

export function Hotspot({
  label,
  x,
  y,
  width,
  height,
  onClick,
  selected = false,
  className = "",
}: {
  label: string;
  x: number;
  y: number;
  width: number;
  height: number;
  onClick: () => void;
  selected?: boolean;
  children?: ReactNode;
  className?: string;
}) {
  const style = {
    left: `${x}%`,
    top: `${y}%`,
    width: `${width}%`,
    height: `${height}%`,
  } satisfies CSSProperties;

  return (
    <button
      type="button"
      className={`hotspot ${selected ? "is-selected" : ""} ${className}`}
      style={style}
      onClick={onClick}
      aria-label={label}
      aria-pressed={selected || undefined}
    />
  );
}
