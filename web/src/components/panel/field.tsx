/** A labelled field in a panel form, with the optional hint under it. */
export function Field({ label, hint, children }: { label: string; hint?: string; children: React.ReactNode }) {
  return (
    <label className="text-muted-foreground flex flex-col gap-1 text-xs">
      {label}
      {children}
      {hint ? <span className="text-xs">{hint}</span> : null}
    </label>
  )
}
