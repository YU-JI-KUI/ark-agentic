import React, { useEffect, useMemo, useState } from 'react'
import { designSlides } from './designSlides'

type DeckTheme = 'dark' | 'light-orange'

function useCurrentSlide(total: number) {
  const readIndex = () => {
    const params = new URLSearchParams(window.location.search)
    const raw = Number(params.get('slide') ?? '1')
    if (Number.isNaN(raw)) return 0
    return Math.min(Math.max(raw - 1, 0), total - 1)
  }

  const [index, setIndex] = useState(readIndex)

  useEffect(() => {
    const onPopState = () => setIndex(readIndex())
    window.addEventListener('popstate', onPopState)
    return () => window.removeEventListener('popstate', onPopState)
  }, [total])

  useEffect(() => {
    const params = new URLSearchParams(window.location.search)
    params.set('slide', String(index + 1))
    const nextUrl = `${window.location.pathname}?${params.toString()}`
    window.history.replaceState({}, '', nextUrl)
  }, [index])

  return { index, setIndex }
}

function useDeckTheme() {
  const readTheme = (): DeckTheme => {
    const params = new URLSearchParams(window.location.search)
    return params.get('theme') === 'light-orange' ? 'light-orange' : 'dark'
  }

  const [theme, setTheme] = useState<DeckTheme>(readTheme)

  useEffect(() => {
    const onPopState = () => setTheme(readTheme())
    window.addEventListener('popstate', onPopState)
    return () => window.removeEventListener('popstate', onPopState)
  }, [])

  useEffect(() => {
    const params = new URLSearchParams(window.location.search)
    params.set('theme', theme)
    const nextUrl = `${window.location.pathname}?${params.toString()}`
    window.history.replaceState({}, '', nextUrl)
  }, [theme])

  return { theme, setTheme }
}

const themeClasses: Record<
  DeckTheme,
  {
    page: string
    header: string
    brand: string
    title: string
    link: string
    progressBox: string
    progressLabel: string
    progressValue: string
    sidebar: string
    sidebarTitle: string
    navActive: string
    navIdle: string
    navSection: string
    navText: string
    main: string
    mainHeader: string
    sectionBadge: string
    slideTitle: string
    subtitle: string
    summary: string
    highlightCard: string
    highlightText: string
    tableWrap: string
    tableHead: string
    tableHeadCell: string
    tableRow: string
    tableCell: string
    tableFirstCell: string
    columnCard: string
    columnTitle: string
    columnItem: string
    bullet: string
    iconsWrap: string
    iconsLabel: string
    iconChip: string
    iconDot: string
    footer: string
    footerText: string
    prevButton: string
    nextButton: string
    themeValue: string
  }
> = {
  dark: {
    page: 'min-h-screen bg-slate-950 text-slate-100',
    header: 'mb-4 flex flex-wrap items-center justify-between gap-3 rounded-2xl border border-white/10 bg-white/5 px-4 py-3 backdrop-blur',
    brand: 'text-xs uppercase tracking-[0.3em] text-orange-300',
    title: 'text-lg font-semibold sm:text-xl text-white',
    link: 'rounded-lg border border-white/10 bg-white/5 px-3 py-2 text-slate-200 transition hover:border-orange-400/50 hover:bg-orange-500/10',
    progressBox: 'rounded-lg border border-white/10 bg-slate-900/80 px-3 py-2',
    progressLabel: 'text-xs uppercase tracking-[0.25em] text-slate-400',
    progressValue: 'mt-1 text-2xl font-semibold text-white',
    sidebar: 'hidden overflow-hidden rounded-3xl border border-white/10 bg-white/5 xl:flex xl:flex-col',
    sidebarTitle: 'border-b border-white/10 px-4 py-3 text-sm font-medium text-slate-300',
    navActive: 'border-orange-400/60 bg-orange-500/15 shadow-lg shadow-orange-500/10',
    navIdle: 'border-white/8 bg-slate-900/50 hover:border-white/20 hover:bg-white/5',
    navSection: 'mb-1 text-[11px] uppercase tracking-[0.25em] text-orange-300/80',
    navText: 'text-sm font-semibold leading-snug text-slate-100',
    main: 'flex min-h-[calc(100vh-148px)] flex-col overflow-hidden rounded-[32px] border border-white/10 bg-[radial-gradient(circle_at_top_right,_rgba(234,85,4,0.16),_transparent_28%),linear-gradient(135deg,_rgba(15,23,42,0.98),_rgba(2,6,23,0.96))] shadow-2xl shadow-black/30',
    mainHeader: 'flex flex-wrap items-start justify-between gap-4 border-b border-white/10 px-6 py-5 lg:px-8',
    sectionBadge: 'mb-2 inline-flex rounded-full border border-orange-400/30 bg-orange-500/10 px-3 py-1 text-xs uppercase tracking-[0.28em] text-orange-200',
    slideTitle: 'text-3xl font-bold leading-tight text-white lg:text-4xl',
    subtitle: 'mt-3 text-lg text-slate-200',
    summary: 'mt-4 max-w-4xl text-base leading-7 text-slate-300 lg:text-lg',
    highlightCard: 'rounded-2xl border border-orange-400/20 bg-orange-500/8 p-4 shadow-lg shadow-orange-950/10',
    highlightText: 'text-sm leading-7 text-orange-50',
    tableWrap: 'overflow-hidden rounded-3xl border border-white/10 bg-white/[0.04]',
    tableHead: 'bg-white/8',
    tableHeadCell: 'border-b border-white/10 px-4 py-4 text-sm font-semibold tracking-wide text-white lg:px-5',
    tableRow: 'align-top odd:bg-white/[0.02]',
    tableCell: 'border-b border-white/10 px-4 py-4 text-sm leading-7 text-slate-200 lg:px-5 lg:text-[15px]',
    tableFirstCell: 'w-40 font-semibold text-white',
    columnCard: 'rounded-3xl border border-white/10 bg-white/[0.04] p-5 lg:p-6',
    columnTitle: 'mb-4 text-xl font-semibold text-white',
    columnItem: 'flex items-start gap-3 text-[15px] leading-7 text-slate-200 lg:text-base',
    bullet: 'mt-2 h-2.5 w-2.5 shrink-0 rounded-full bg-orange-400 shadow-[0_0_0_4px_rgba(234,85,4,0.14)]',
    iconsWrap: 'mt-6 rounded-3xl border border-emerald-400/20 bg-emerald-500/8 p-5 lg:p-6',
    iconsLabel: 'mb-3 text-sm font-semibold uppercase tracking-[0.25em] text-emerald-200',
    iconChip: 'inline-flex items-center gap-2 rounded-full border border-white/10 bg-slate-950/45 px-4 py-2 text-sm text-emerald-50',
    iconDot: 'inline-block h-2.5 w-2.5 rounded-full bg-emerald-300 shadow-[0_0_0_4px_rgba(16,185,129,0.14)]',
    footer: 'flex flex-wrap items-center justify-between gap-3 border-t border-white/10 px-6 py-4 lg:px-8',
    footerText: 'text-sm text-slate-400',
    prevButton: 'rounded-xl border border-white/10 bg-white/5 px-4 py-2 text-sm text-slate-100 transition enabled:hover:border-white/25 enabled:hover:bg-white/10 disabled:cursor-not-allowed disabled:opacity-40',
    nextButton: 'rounded-xl border border-orange-400/40 bg-orange-500/15 px-4 py-2 text-sm text-orange-50 transition enabled:hover:border-orange-300 enabled:hover:bg-orange-500/25 disabled:cursor-not-allowed disabled:opacity-40',
    themeValue: 'mt-1 text-sm font-semibold text-orange-300',
  },
  'light-orange': {
    page: 'min-h-screen bg-[linear-gradient(180deg,_#fff7ed_0%,_#fffaf5_48%,_#ffffff_100%)] text-slate-900',
    header: 'mb-4 flex flex-wrap items-center justify-between gap-3 rounded-2xl border border-orange-200 bg-white/90 px-4 py-3 shadow-sm backdrop-blur',
    brand: 'text-xs uppercase tracking-[0.3em] text-orange-600',
    title: 'text-lg font-semibold sm:text-xl text-slate-900',
    link: 'rounded-lg border border-orange-200 bg-orange-50 px-3 py-2 text-orange-700 transition hover:border-orange-300 hover:bg-orange-100',
    progressBox: 'rounded-lg border border-orange-200 bg-white px-3 py-2',
    progressLabel: 'text-xs uppercase tracking-[0.25em] text-orange-500',
    progressValue: 'mt-1 text-2xl font-semibold text-orange-700',
    sidebar: 'hidden overflow-hidden rounded-3xl border border-orange-200 bg-white/85 xl:flex xl:flex-col shadow-sm',
    sidebarTitle: 'border-b border-orange-100 px-4 py-3 text-sm font-medium text-orange-700',
    navActive: 'border-orange-400 bg-orange-100 shadow-lg shadow-orange-200/60',
    navIdle: 'border-orange-100 bg-white/80 hover:border-orange-200 hover:bg-orange-50',
    navSection: 'mb-1 text-[11px] uppercase tracking-[0.25em] text-orange-500',
    navText: 'text-sm font-semibold leading-snug text-slate-800',
    main: 'flex min-h-[calc(100vh-148px)] flex-col overflow-hidden rounded-[32px] border border-orange-200 bg-[radial-gradient(circle_at_top_right,_rgba(251,146,60,0.22),_transparent_26%),linear-gradient(180deg,_rgba(255,247,237,0.96),_rgba(255,255,255,0.98))] shadow-xl shadow-orange-100/60',
    mainHeader: 'flex flex-wrap items-start justify-between gap-4 border-b border-orange-100 px-6 py-5 lg:px-8',
    sectionBadge: 'mb-2 inline-flex rounded-full border border-orange-300 bg-orange-100 px-3 py-1 text-xs uppercase tracking-[0.28em] text-orange-700',
    slideTitle: 'text-3xl font-bold leading-tight text-slate-900 lg:text-4xl',
    subtitle: 'mt-3 text-lg text-slate-700',
    summary: 'mt-4 max-w-4xl text-base leading-7 text-slate-600 lg:text-lg',
    highlightCard: 'rounded-2xl border border-orange-200 bg-white p-4 shadow-sm',
    highlightText: 'text-sm leading-7 text-slate-700',
    tableWrap: 'overflow-hidden rounded-3xl border border-orange-200 bg-white shadow-sm',
    tableHead: 'bg-orange-100',
    tableHeadCell: 'border-b border-orange-200 px-4 py-4 text-sm font-semibold tracking-wide text-orange-800 lg:px-5',
    tableRow: 'align-top odd:bg-orange-50/40',
    tableCell: 'border-b border-orange-100 px-4 py-4 text-sm leading-7 text-slate-700 lg:px-5 lg:text-[15px]',
    tableFirstCell: 'w-40 font-semibold text-slate-900',
    columnCard: 'rounded-3xl border border-orange-200 bg-white p-5 lg:p-6 shadow-sm',
    columnTitle: 'mb-4 text-xl font-semibold text-slate-900',
    columnItem: 'flex items-start gap-3 text-[15px] leading-7 text-slate-700 lg:text-base',
    bullet: 'mt-2 h-2.5 w-2.5 shrink-0 rounded-full bg-orange-500 shadow-[0_0_0_4px_rgba(251,146,60,0.18)]',
    iconsWrap: 'mt-6 rounded-3xl border border-orange-200 bg-orange-50/80 p-5 lg:p-6',
    iconsLabel: 'mb-3 text-sm font-semibold uppercase tracking-[0.25em] text-orange-700',
    iconChip: 'inline-flex items-center gap-2 rounded-full border border-orange-200 bg-white px-4 py-2 text-sm text-slate-700',
    iconDot: 'inline-block h-2.5 w-2.5 rounded-full bg-orange-500 shadow-[0_0_0_4px_rgba(251,146,60,0.16)]',
    footer: 'flex flex-wrap items-center justify-between gap-3 border-t border-orange-100 px-6 py-4 lg:px-8',
    footerText: 'text-sm text-slate-500',
    prevButton: 'rounded-xl border border-orange-200 bg-white px-4 py-2 text-sm text-slate-700 transition enabled:hover:border-orange-300 enabled:hover:bg-orange-50 disabled:cursor-not-allowed disabled:opacity-40',
    nextButton: 'rounded-xl border border-orange-300 bg-orange-500 px-4 py-2 text-sm text-white transition enabled:hover:border-orange-400 enabled:hover:bg-orange-600 disabled:cursor-not-allowed disabled:opacity-40',
    themeValue: 'mt-1 text-sm font-semibold text-orange-700',
  },
}

export default function DesignDeck() {
  const total = designSlides.length
  const { index, setIndex } = useCurrentSlide(total)
  const { theme, setTheme } = useDeckTheme()
  const slide = designSlides[index]
  const styles = themeClasses[theme]

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'ArrowRight' || event.key === 'PageDown' || event.key === ' ') {
        event.preventDefault()
        setIndex((current) => Math.min(current + 1, total - 1))
        return
      }

      if (event.key === 'ArrowLeft' || event.key === 'PageUp') {
        event.preventDefault()
        setIndex((current) => Math.max(current - 1, 0))
        return
      }

      if (event.key === 'ArrowUp') {
        event.preventDefault()
        setTheme('dark')
        return
      }

      if (event.key === 'ArrowDown') {
        event.preventDefault()
        setTheme('light-orange')
        return
      }

      if (event.key === 'Home') {
        event.preventDefault()
        setIndex(0)
        return
      }

      if (event.key === 'End') {
        event.preventDefault()
        setIndex(total - 1)
      }
    }

    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [setIndex, setTheme, total])

  const progress = useMemo(() => `${index + 1} / ${total}`, [index, total])
  const themeLabel = theme === 'dark' ? '原始深色' : '橙白风格'
  const contentLayout =
    slide.layout === 'stack'
      ? 'grid-cols-1'
      : slide.columns && slide.columns.length >= 3
        ? '2xl:grid-cols-3'
        : slide.columns && slide.columns.length >= 2
          ? '2xl:grid-cols-2'
          : 'grid-cols-1'

  return (
    <div className={styles.page}>
      <div className="mx-auto flex min-h-screen max-w-[1800px] flex-col px-4 py-4 sm:px-6 lg:px-8">
        <header className={styles.header}>
          <div>
            <div className={styles.brand}>Design Deck</div>
            <h1 className={styles.title}>ark-agentic 技术分享可视化稿</h1>
          </div>

          <div className="flex flex-wrap items-center gap-2 text-sm">
            <div className={styles.progressBox}>
              <div className={styles.progressLabel}>当前主题</div>
              <div className={styles.themeValue}>{themeLabel}</div>
            </div>
            <a href="/" className={styles.link}>
              返回 Architect
            </a>
            <div className={styles.progressBox}>
              <div className={styles.progressValue}>{progress}</div>
            </div>
          </div>
        </header>

        <div className="grid flex-1 gap-4 xl:grid-cols-[260px_minmax(0,1fr)]">
          <aside className={styles.sidebar}>
            <div className={styles.sidebarTitle}>目录 / 快速跳转</div>
            <div className="flex-1 space-y-2 overflow-y-auto px-3 py-3">
              {designSlides.map((item, itemIndex) => {
                const active = itemIndex === index
                return (
                  <button
                    key={item.id}
                    type="button"
                    onClick={() => setIndex(itemIndex)}
                    className={`w-full rounded-2xl border px-3 py-3 text-left transition ${active ? styles.navActive : styles.navIdle}`}
                  >
                    <div className={styles.navSection}>{item.section}</div>
                    <div className={styles.navText}>{item.title}</div>
                  </button>
                )
              })}
            </div>
          </aside>

          <main className={styles.main}>
            <div className={styles.mainHeader}>
              <div className="max-w-4xl">
                <div className={styles.sectionBadge}>{slide.section}</div>
                <h2 className={styles.slideTitle}>{slide.title}</h2>
                {slide.subtitle ? <p className={styles.subtitle}>{slide.subtitle}</p> : null}
                {slide.summary ? <p className={styles.summary}>{slide.summary}</p> : null}
              </div>

              <div className={`${styles.progressBox} hidden lg:block`}>
                <div className={styles.progressLabel}>当前页</div>
                <div className={styles.progressValue}>{progress}</div>
              </div>
            </div>

            <div className="flex-1 overflow-y-auto px-6 py-6 lg:px-8 lg:py-8">
              {slide.highlights?.length ? (
                <section className="mb-6 grid gap-4 lg:grid-cols-3">
                  {slide.highlights.map((item) => (
                    <article key={item} className={styles.highlightCard}>
                      <div className={styles.highlightText}>{item}</div>
                    </article>
                  ))}
                </section>
              ) : null}

              {slide.table ? (
                <section className={styles.tableWrap}>
                  <div className="overflow-x-auto">
                    <table className="min-w-full border-collapse text-left">
                      <thead className={styles.tableHead}>
                        <tr>
                          {slide.table.headers.map((header) => (
                            <th key={header} className={styles.tableHeadCell}>
                              {header}
                            </th>
                          ))}
                        </tr>
                      </thead>
                      <tbody>
                        {slide.table.rows.map((row) => (
                          <tr key={row.join('|')} className={styles.tableRow}>
                            {row.map((cell, cellIndex) => (
                              <td key={`${row[0]}-${cellIndex}`} className={`${styles.tableCell} ${cellIndex === 0 ? styles.tableFirstCell : ''}`}>
                                {cell}
                              </td>
                            ))}
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </section>
              ) : null}

              {slide.columns?.length ? (
                <section className={`grid gap-5 ${contentLayout}`}>
                  {slide.columns.map((column) => (
                    <article key={column.title} className={styles.columnCard}>
                      <h3 className={styles.columnTitle}>{column.title}</h3>
                      <ul className="space-y-3">
                        {column.items.map((item) => (
                          <li key={item} className={styles.columnItem}>
                            <span className={styles.bullet} />
                            <span>{item}</span>
                          </li>
                        ))}
                      </ul>
                    </article>
                  ))}
                </section>
              ) : null}

              {slide.icons?.length ? (
                <section className={styles.iconsWrap}>
                  <div className={styles.iconsLabel}>相关技术</div>
                  <div className="flex flex-wrap gap-3">
                    {slide.icons.map((item) => (
                      <div key={item} className={styles.iconChip}>
                        <span className={styles.iconDot} />
                        <span>{item}</span>
                      </div>
                    ))}
                  </div>
                </section>
              ) : null}
            </div>

            <footer className={styles.footer}>
              <div className={styles.footerText}>支持键盘翻页：← → / PageUp / PageDown / Home / End；主题切换：↑ 原始深色 / ↓ 橙白风格</div>
              <div className="flex items-center gap-2">
                <button
                  type="button"
                  onClick={() => setIndex((current) => Math.max(current - 1, 0))}
                  disabled={index === 0}
                  className={styles.prevButton}
                >
                  ← 上一页
                </button>
                <button
                  type="button"
                  onClick={() => setIndex((current) => Math.min(current + 1, total - 1))}
                  disabled={index === total - 1}
                  className={styles.nextButton}
                >
                  下一页 →
                </button>
              </div>
            </footer>
          </main>
        </div>
      </div>
    </div>
  )
}
