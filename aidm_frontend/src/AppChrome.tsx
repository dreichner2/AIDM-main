import { Circle } from 'lucide-react'
import type { ReactNode } from 'react'

export type ThinIconName =
  | 'archive'
  | 'bolt'
  | 'book'
  | 'briefcase'
  | 'chevron'
  | 'cloud'
  | 'cog'
  | 'cube'
  | 'dice'
  | 'dot'
  | 'map'
  | 'refresh'
  | 'send'
  | 'settings'
  | 'smile'
  | 'spark'
  | 'turns'

export function StatusDot({
  label,
  tone = 'good',
}: {
  label: string
  tone?: 'good' | 'neutral' | 'warn'
}) {
  return (
    <span className={`status-dot ${tone}`}>
      <Circle size={8} fill="currentColor" />
      {label}
    </span>
  )
}

export function ThinIcon({
  name,
  size = 18,
  className,
}: {
  name: ThinIconName
  size?: number
  className?: string
}) {
  const common = {
    fill: 'none',
    stroke: 'currentColor',
    strokeLinecap: 'round' as const,
    strokeLinejoin: 'round' as const,
    strokeWidth: 1.35,
  }
  return (
    <svg
      aria-hidden="true"
      className={className}
      width={size}
      height={size}
      viewBox="0 0 24 24"
    >
      {name === 'archive' ? (
        <>
          <path {...common} d="M5 6.5h14v12H5z" />
          <path {...common} d="M8 6.5V4h8v2.5M9 10h6" />
        </>
      ) : null}
      {name === 'bolt' ? <path {...common} d="M13 2 5.5 13h5L9 22l8-12h-5z" /> : null}
      {name === 'book' ? (
        <>
          <path {...common} d="M6 4.5h8.5A2.5 2.5 0 0 1 17 7v12H8.5A2.5 2.5 0 0 1 6 16.5z" />
          <path {...common} d="M17 7h1.5v12H17M9 8h4" />
        </>
      ) : null}
      {name === 'briefcase' ? (
        <>
          <path {...common} d="M4.5 8h15v10.5h-15z" />
          <path {...common} d="M9 8V5.5h6V8M4.5 12h15" />
        </>
      ) : null}
      {name === 'chevron' ? <path {...common} d="m7 9 5 5 5-5" /> : null}
      {name === 'cloud' ? (
        <path {...common} d="M7.5 18h9a4 4 0 0 0 .2-8 5.6 5.6 0 0 0-10.7 1.8A3.2 3.2 0 0 0 7.5 18Z" />
      ) : null}
      {name === 'cog' ? (
        <>
          <circle {...common} cx="12" cy="12" r="2.8" />
          <path {...common} d="M12 3.5v2M12 18.5v2M4.6 7.8l1.7 1M17.7 15.2l1.7 1M4.6 16.2l1.7-1M17.7 8.8l1.7-1M3.5 12h2M18.5 12h2" />
        </>
      ) : null}
      {name === 'cube' ? (
        <>
          <path {...common} d="m12 3 7 4v10l-7 4-7-4V7z" />
          <path {...common} d="m5 7 7 4 7-4M12 11v10" />
        </>
      ) : null}
      {name === 'dice' ? (
        <>
          <rect {...common} x="5" y="5" width="14" height="14" rx="2" />
          <circle cx="9" cy="9" r="1" fill="currentColor" />
          <circle cx="15" cy="15" r="1" fill="currentColor" />
          <circle cx="15" cy="9" r="1" fill="currentColor" />
          <circle cx="9" cy="15" r="1" fill="currentColor" />
        </>
      ) : null}
      {name === 'dot' ? <circle cx="12" cy="12" r="2.3" fill="currentColor" /> : null}
      {name === 'map' ? (
        <>
          <path {...common} d="m4 6 5-2 6 2 5-2v14l-5 2-6-2-5 2z" />
          <path {...common} d="M9 4v14M15 6v14" />
        </>
      ) : null}
      {name === 'refresh' ? (
        <>
          <path {...common} d="M18.5 8.5A7 7 0 0 0 6 6.3L4.5 8.5" />
          <path {...common} d="M4.5 4.5v4h4M5.5 15.5A7 7 0 0 0 18 17.7l1.5-2.2" />
          <path {...common} d="M19.5 19.5v-4h-4" />
        </>
      ) : null}
      {name === 'send' ? <path {...common} d="M4 12.5 20 4l-5.8 16-3.1-6.9zM11.1 13.1 20 4" /> : null}
      {name === 'settings' ? (
        <>
          <circle {...common} cx="12" cy="12" r="3" />
          <path {...common} d="M12 4.5v2M12 17.5v2M5.6 6.7 7 8.1M17 15.9l1.4 1.4M4.5 12h2M17.5 12h2M5.6 17.3 7 15.9M17 8.1l1.4-1.4" />
        </>
      ) : null}
      {name === 'smile' ? (
        <>
          <circle {...common} cx="12" cy="12" r="8" />
          <path {...common} d="M8.8 14.2a4.4 4.4 0 0 0 6.4 0" />
          <path {...common} d="M9 10h.01M15 10h.01" />
        </>
      ) : null}
      {name === 'spark' ? <path {...common} d="m12 3 1.7 5.1L19 10l-5.3 1.9L12 17l-1.7-5.1L5 10l5.3-1.9z" /> : null}
      {name === 'turns' ? (
        <>
          <path {...common} d="M6 7h9a3 3 0 0 1 0 6H8" />
          <path {...common} d="m9 4-3 3 3 3M18 17H9" />
        </>
      ) : null}
    </svg>
  )
}

export function ToolbarButton({
  ariaControls,
  ariaExpanded,
  children,
  disabled,
  icon,
  id,
  onClick,
  title,
}: {
  ariaControls?: string
  ariaExpanded?: boolean
  children?: ReactNode
  disabled?: boolean
  icon: ReactNode
  id?: string
  onClick?: () => void
  title: string
}) {
  return (
    <button
      type="button"
      id={id}
      className="toolbar-button"
      disabled={disabled}
      onClick={onClick}
      title={title}
      aria-label={title}
      aria-controls={ariaControls}
      aria-expanded={ariaExpanded}
    >
      {icon}
      {children ? <span>{children}</span> : null}
    </button>
  )
}

export function Thumbnail({
  index,
  selected,
  src,
  title,
}: {
  index: number
  selected?: boolean
  src: string
  title: string
}) {
  return (
    <span className={`thumb thumb-${index} ${selected ? 'selected-thumb' : ''}`}>
      <img src={src} alt="" aria-hidden="true" />
      <span className="thumb-letter">{title.slice(0, 1).toUpperCase()}</span>
    </span>
  )
}

export function NavItem({
  icon,
  label,
  onClick,
  selected,
}: {
  icon: ReactNode
  label: string
  onClick?: () => void
  selected?: boolean
}) {
  return (
    <button
      type="button"
      className={`nav-item ${selected ? 'active' : ''}`}
      aria-current={selected ? 'page' : undefined}
      onClick={onClick}
    >
      {icon}
      <span>{label}</span>
    </button>
  )
}
