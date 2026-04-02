import { ReactNode } from 'react'

export function Card({ title, children }: { title?: string; children: ReactNode }) {
  return (
    <section className="card">
      {title ? <div className="card-title">{title}</div> : null}
      <div>{children}</div>
    </section>
  )
}
