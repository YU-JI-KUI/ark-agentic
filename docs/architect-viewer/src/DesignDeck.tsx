import React, { useEffect, useMemo, useState } from 'react'
import { designSlides } from './designSlides'

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
  }, [total])

  useEffect(() => {
    const params = new URLSearchParams(window.location.search)
    params.set('slide', String(index + 1))
    const nextUrl = `${window.location.pathname}?${params.toString()}`
    window.history.replaceState({}, '', nextUrl)
  }, [index])

  return { index, setIndex }
}

export default function DesignDeck() {
  const total = designSlides.length
  const { index, setIndex } = useCurrentSlide(total)
  const slide = designSlides[index]

  const progress = useMemo(() => `${index + 1} / ${total}`, [index, total])
  const contentLayout =
    slide.layout === 'stack'
      ? 'grid-cols-1'
      : slide.columns && slide.columns.length >= 3
        ? '2xl:grid-cols-3'
        : slide.columns && slide.columns.length >= 2
          ? '2xl:grid-cols-2'
          : 'grid-cols-1'

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100">
      <div className="mx-auto flex min-h-screen max-w-[1800px] flex-col px-4 py-4 sm:px-6 lg:px-8">
        <header className="mb-4 flex flex-wrap items-center justify-between gap-3 rounded-2xl border border-white/10 bg-white/5 px-4 py-3 backdrop-blur">
          <div>
            <div className="text-xs uppercase tracking-[0.3em] text-orange-300">Design Deck</div>
            <h1 className="text-lg font-semibold sm:text-xl">ark-agentic 技术分享可视化稿</h1>
          </div>

          <div className="flex flex-wrap items-center gap-2 text-sm">
            <a
              href="/"
              className="rounded-lg border border-white/10 bg-white/5 px-3 py-2 text-slate-200 transition hover:border-orange-400/50 hover:bg-orange-500/10"
            >
              返回 Architect
            </a>
            <div className="rounded-lg border border-white/10 bg-slate-900/80 px-3 py-2 text-slate-300">
              {progress}
            </div>
          </div>
        </header>

        <div className="grid flex-1 gap-4 xl:grid-cols-[260px_minmax(0,1fr)]">
          <aside className="hidden overflow-hidden rounded-3xl border border-white/10 bg-white/5 xl:flex xl:flex-col">
            <div className="border-b border-white/10 px-4 py-3 text-sm font-medium text-slate-300">目录 / 快速跳转</div>
            <div className="flex-1 space-y-2 overflow-y-auto px-3 py-3">
              {designSlides.map((item, itemIndex) => {
                const active = itemIndex === index
                return (
                  <button
                    key={item.id}
                    type="button"
                    onClick={() => setIndex(itemIndex)}
                    className={`w-full rounded-2xl border px-3 py-3 text-left transition ${
                      active
                        ? 'border-orange-400/60 bg-orange-500/15 shadow-lg shadow-orange-500/10'
                        : 'border-white/8 bg-slate-900/50 hover:border-white/20 hover:bg-white/5'
                    }`}
                  >
                    <div className="mb-1 text-[11px] uppercase tracking-[0.25em] text-orange-300/80">{item.section}</div>
                    <div className="text-sm font-semibold leading-snug text-slate-100">{item.title}</div>
                  </button>
                )
              })}
            </div>
          </aside>

          <main className="flex min-h-[calc(100vh-148px)] flex-col overflow-hidden rounded-[32px] border border-white/10 bg-[radial-gradient(circle_at_top_right,_rgba(234,85,4,0.16),_transparent_28%),linear-gradient(135deg,_rgba(15,23,42,0.98),_rgba(2,6,23,0.96))] shadow-2xl shadow-black/30">
            <div className="flex flex-wrap items-start justify-between gap-4 border-b border-white/10 px-6 py-5 lg:px-8">
              <div className="max-w-4xl">
                <div className="mb-2 inline-flex rounded-full border border-orange-400/30 bg-orange-500/10 px-3 py-1 text-xs uppercase tracking-[0.28em] text-orange-200">
                  {slide.section}
                </div>
                <h2 className="text-3xl font-bold leading-tight text-white lg:text-4xl">{slide.title}</h2>
                {slide.subtitle ? <p className="mt-3 text-lg text-slate-200">{slide.subtitle}</p> : null}
                {slide.summary ? <p className="mt-4 max-w-4xl text-base leading-7 text-slate-300 lg:text-lg">{slide.summary}</p> : null}
              </div>

              <div className="hidden rounded-2xl border border-white/10 bg-white/5 px-4 py-3 text-right lg:block">
                <div className="text-xs uppercase tracking-[0.25em] text-slate-400">当前页</div>
                <div className="mt-1 text-2xl font-semibold text-white">{progress}</div>
              </div>
            </div>

            <div className="flex-1 overflow-y-auto px-6 py-6 lg:px-8 lg:py-8">
              {slide.highlights?.length ? (
                <section className="mb-6 grid gap-4 lg:grid-cols-3">
                  {slide.highlights.map((item) => (
                    <article key={item} className="rounded-2xl border border-orange-400/20 bg-orange-500/8 p-4 shadow-lg shadow-orange-950/10">
                      <div className="text-sm leading-7 text-orange-50">{item}</div>
                    </article>
                  ))}
                </section>
              ) : null}

              {slide.table ? (
                <section className="overflow-hidden rounded-3xl border border-white/10 bg-white/[0.04]">
                  <div className="overflow-x-auto">
                    <table className="min-w-full border-collapse text-left">
                      <thead className="bg-white/8">
                        <tr>
                          {slide.table.headers.map((header) => (
                            <th
                              key={header}
                              className="border-b border-white/10 px-4 py-4 text-sm font-semibold tracking-wide text-white lg:px-5"
                            >
                              {header}
                            </th>
                          ))}
                        </tr>
                      </thead>
                      <tbody>
                        {slide.table.rows.map((row) => (
                          <tr key={row.join('|')} className="align-top odd:bg-white/[0.02]">
                            {row.map((cell, cellIndex) => (
                              <td
                                key={`${row[0]}-${cellIndex}`}
                                className={`border-b border-white/10 px-4 py-4 text-sm leading-7 text-slate-200 lg:px-5 lg:text-[15px] ${
                                  cellIndex === 0 ? 'w-40 font-semibold text-white' : ''
                                }`}
                              >
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
                    <article key={column.title} className="rounded-3xl border border-white/10 bg-white/[0.04] p-5 lg:p-6">
                      <h3 className="mb-4 text-xl font-semibold text-white">{column.title}</h3>
                      <ul className="space-y-3">
                        {column.items.map((item) => (
                          <li key={item} className="flex items-start gap-3 text-[15px] leading-7 text-slate-200 lg:text-base">
                            <span className="mt-2 h-2.5 w-2.5 shrink-0 rounded-full bg-orange-400 shadow-[0_0_0_4px_rgba(234,85,4,0.14)]" />
                            <span>{item}</span>
                          </li>
                        ))}
                      </ul>
                    </article>
                  ))}
                </section>
              ) : null}

              {slide.icons?.length ? (
                <section className="mt-6 rounded-3xl border border-emerald-400/20 bg-emerald-500/8 p-5 lg:p-6">
                  <div className="mb-3 text-sm font-semibold uppercase tracking-[0.25em] text-emerald-200">相关技术</div>
                  <div className="flex flex-wrap gap-3">
                    {slide.icons.map((item) => (
                      <div
                        key={item}
                        className="inline-flex items-center gap-2 rounded-full border border-white/10 bg-slate-950/45 px-4 py-2 text-sm text-emerald-50"
                      >
                        <span className="inline-block h-2.5 w-2.5 rounded-full bg-emerald-300 shadow-[0_0_0_4px_rgba(16,185,129,0.14)]" />
                        <span>{item}</span>
                      </div>
                    ))}
                  </div>
                </section>
              ) : null}
            </div>

            <footer className="flex flex-wrap items-center justify-between gap-3 border-t border-white/10 px-6 py-4 lg:px-8">
              <div className="text-sm text-slate-400">支持键盘翻页：← → / PageUp / PageDown / Home / End</div>
              <div className="flex items-center gap-2">
                <button
                  type="button"
                  onClick={() => setIndex((current) => Math.max(current - 1, 0))}
                  disabled={index === 0}
                  className="rounded-xl border border-white/10 bg-white/5 px-4 py-2 text-sm text-slate-100 transition enabled:hover:border-white/25 enabled:hover:bg-white/10 disabled:cursor-not-allowed disabled:opacity-40"
                >
                  ← 上一页
                </button>
                <button
                  type="button"
                  onClick={() => setIndex((current) => Math.min(current + 1, total - 1))}
                  disabled={index === total - 1}
                  className="rounded-xl border border-orange-400/40 bg-orange-500/15 px-4 py-2 text-sm text-orange-50 transition enabled:hover:border-orange-300 enabled:hover:bg-orange-500/25 disabled:cursor-not-allowed disabled:opacity-40"
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
