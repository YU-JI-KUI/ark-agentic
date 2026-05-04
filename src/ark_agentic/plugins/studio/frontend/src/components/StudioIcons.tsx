import type { SVGProps } from 'react'

type IconProps = SVGProps<SVGSVGElement>

function IconBase(props: IconProps) {
  return (
    <svg
      aria-hidden="true"
      fill="none"
      height="20"
      stroke="currentColor"
      strokeLinecap="round"
      strokeLinejoin="round"
      strokeWidth="1.8"
      viewBox="0 0 24 24"
      width="20"
      {...props}
    />
  )
}

export function OverviewIcon(props: IconProps) {
  return (
    <IconBase {...props}>
      <path d="M3 12.5 12 4l9 8.5" />
      <path d="M5.5 10.5V20h13V10.5" />
      <path d="M9.5 20v-5h5v5" />
    </IconBase>
  )
}

export function UsersIcon(props: IconProps) {
  return (
    <IconBase {...props}>
      <path d="M17 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2" />
      <circle cx="9" cy="7" r="4" />
      <path d="M23 21v-2a4 4 0 0 0-3-3.87" />
      <path d="M16 3.13a4 4 0 0 1 0 7.75" />
    </IconBase>
  )
}

export function SkillsIcon(props: IconProps) {
  return (
    <IconBase {...props}>
      <path d="M8 5.5h8" />
      <path d="M8 10h8" />
      <path d="M8 14.5h5" />
      <path d="M4.5 5.5h.01" />
      <path d="M4.5 10h.01" />
      <path d="M4.5 14.5h.01" />
      <path d="m16.5 18 1.5 1.5 3-3" />
    </IconBase>
  )
}

export function ToolsIcon(props: IconProps) {
  return (
    <IconBase {...props}>
      <path d="m14 7 3 3" />
      <path d="m4 20 6.5-6.5" />
      <path d="m11.5 5.5 2-2a2.1 2.1 0 0 1 3 3l-2 2" />
      <path d="m10 7 7 7" />
      <path d="m8.5 11.5-5 5a2.1 2.1 0 1 0 3 3l5-5" />
    </IconBase>
  )
}

export function SessionsIcon(props: IconProps) {
  return (
    <IconBase {...props}>
      <path d="M4 5.5h16v10H8l-4 3v-13Z" />
      <path d="M8 10h8" />
      <path d="M8 7.5h5" />
    </IconBase>
  )
}

export function MemoryIcon(props: IconProps) {
  return (
    <IconBase {...props}>
      <path d="M6.5 4.5h10a2 2 0 0 1 2 2v13l-4-2-4 2-4-2-4 2v-13a2 2 0 0 1 2-2h2" />
      <path d="M8.5 8h6" />
      <path d="M8.5 11.5h6" />
    </IconBase>
  )
}

export function AgentIcon(props: IconProps) {
  return (
    <IconBase {...props}>
      <rect height="10" rx="3" width="12" x="6" y="8" />
      <path d="M12 4.5v3" />
      <path d="M9.5 12.5h.01" />
      <path d="M14.5 12.5h.01" />
      <path d="M9 17.5v2" />
      <path d="M15 17.5v2" />
      <path d="M8.5 2.5 12 4.5l3.5-2" />
    </IconBase>
  )
}

export function SearchIcon(props: IconProps) {
  return (
    <IconBase {...props}>
      <circle cx="11" cy="11" r="6.5" />
      <path d="m16 16 4 4" />
    </IconBase>
  )
}

export function PlusIcon(props: IconProps) {
  return (
    <IconBase {...props}>
      <path d="M12 5v14" />
      <path d="M5 12h14" />
    </IconBase>
  )
}

export function RefreshIcon(props: IconProps) {
  return (
    <IconBase {...props}>
      <path d="M20 6v5h-5" />
      <path d="M4 18v-5h5" />
      <path d="M19 11a7 7 0 0 0-12-3l-2 3" />
      <path d="M5 13a7 7 0 0 0 12 3l2-3" />
    </IconBase>
  )
}

export function LogoutIcon(props: IconProps) {
  return (
    <IconBase {...props}>
      <path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4" />
      <path d="M16 17l5-5-5-5" />
      <path d="M21 12H9" />
    </IconBase>
  )
}

export function SparkIcon(props: IconProps) {
  return (
    <IconBase {...props}>
      <path d="m12 3 1.8 5.2L19 10l-5.2 1.8L12 17l-1.8-5.2L5 10l5.2-1.8L12 3Z" />
      <path d="m5 17 1 3" />
      <path d="m18 16 1 3" />
    </IconBase>
  )
}

export function TraceIcon(props: IconProps) {
  return (
    <IconBase {...props}>
      <path d="M4 6h5v5H4z" />
      <path d="M15 13h5v5h-5z" />
      <path d="M9 8.5h3a3 3 0 0 1 3 3v1.5" />
    </IconBase>
  )
}

export function ChevronRightIcon(props: IconProps) {
  return (
    <IconBase {...props}>
      <path d="m9 6 6 6-6 6" />
    </IconBase>
  )
}

export function CopyIcon(props: IconProps) {
  return (
    <IconBase {...props}>
      <rect height="11" rx="2" width="11" x="9" y="9" />
      <path d="M15 9V6a2 2 0 0 0-2-2H6a2 2 0 0 0-2 2v7a2 2 0 0 0 2 2h3" />
    </IconBase>
  )
}

export function ExpandIcon(props: IconProps) {
  return (
    <IconBase {...props}>
      <path d="M8 3H3v5" />
      <path d="M16 3h5v5" />
      <path d="M21 16v5h-5" />
      <path d="M3 16v5h5" />
      <path d="m3 8 6-5" />
      <path d="m15 3 6 5" />
      <path d="m21 16-6 5" />
      <path d="m9 21-6-5" />
    </IconBase>
  )
}

export function CollapseIcon(props: IconProps) {
  return (
    <IconBase {...props}>
      <path d="M8 8H3V3" />
      <path d="m3 3 6 6" />
      <path d="M16 8h5V3" />
      <path d="m21 3-6 6" />
      <path d="M21 16h-5v5" />
      <path d="m15 15 6 6" />
      <path d="M8 16H3v5" />
      <path d="m3 21 6-6" />
    </IconBase>
  )
}

export function CloseIcon(props: IconProps) {
  return (
    <IconBase {...props}>
      <path d="m6 6 12 12" />
      <path d="M18 6 6 18" />
    </IconBase>
  )
}

export function SendIcon(props: IconProps) {
  return (
    <IconBase {...props}>
      <path d="m22 2-7 20-4-9-9-4Z" />
      <path d="M22 2 11 13" />
    </IconBase>
  )
}

export function SunIcon(props: IconProps) {
  return (
    <IconBase {...props}>
      <circle cx="12" cy="12" r="4" />
      <path d="M12 2v2" />
      <path d="M12 20v2" />
      <path d="m4.93 4.93 1.41 1.41" />
      <path d="m17.66 17.66 1.41 1.41" />
      <path d="M2 12h2" />
      <path d="M20 12h2" />
      <path d="m6.34 17.66-1.41 1.41" />
      <path d="m19.07 4.93-1.41 1.41" />
    </IconBase>
  )
}

export function MoonIcon(props: IconProps) {
  return (
    <IconBase {...props}>
      <path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79Z" />
    </IconBase>
  )
}

export function RobotIcon(props: IconProps) {
  return (
    <IconBase {...props}>
      <rect height="11" rx="3" width="14" x="5" y="8" />
      <path d="M12 4v4" />
      <path d="M9 13h.01" />
      <path d="M15 13h.01" />
      <path d="M8 19v2" />
      <path d="M16 19v2" />
      <path d="M2.5 11.5H5" />
      <path d="M19 11.5h2.5" />
    </IconBase>
  )
}

export function DownloadIcon(props: IconProps) {
  return (
    <IconBase {...props}>
      <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
      <path d="m7 10 5 5 5-5" />
      <path d="M12 15V3" />
    </IconBase>
  )
}

export function BoltIcon(props: IconProps) {
  return (
    <IconBase {...props}>
      <path d="M13 2 3 14h8l-1 8 10-12h-8l1-8Z" fill="currentColor" stroke="none" />
    </IconBase>
  )
}

export function MoreIcon(props: IconProps) {
  return (
    <IconBase {...props}>
      <circle cx="5" cy="12" r="1.5" fill="currentColor" stroke="none" />
      <circle cx="12" cy="12" r="1.5" fill="currentColor" stroke="none" />
      <circle cx="19" cy="12" r="1.5" fill="currentColor" stroke="none" />
    </IconBase>
  )
}

export function FilterIcon(props: IconProps) {
  return (
    <IconBase {...props}>
      <path d="M22 3H2l8 9.46V19l4 2v-8.54L22 3Z" />
    </IconBase>
  )
}
