import {
  type ReactNode,
  type RefObject,
} from 'react'

type ModalShellProps = {
  children: ReactNode
  className?: string
  describedBy?: string
  dialogRef: RefObject<HTMLElement | null>
  labelledBy: string
  onClose: () => void
  closeDisabled?: boolean
}

export function ModalShell({
  children,
  className = 'campaign-dialog',
  closeDisabled = false,
  describedBy,
  dialogRef,
  labelledBy,
  onClose,
}: ModalShellProps) {
  return (
    <div
      className="modal-backdrop"
      role="presentation"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget && !closeDisabled) {
          onClose()
        }
      }}
    >
      <section
        ref={dialogRef}
        className={className}
        role="dialog"
        aria-modal="true"
        aria-labelledby={labelledBy}
        aria-describedby={describedBy}
      >
        {children}
      </section>
    </div>
  )
}
