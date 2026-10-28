import Markdown from 'react-markdown'
import remarkGfm from 'remark-gfm'

export default function MarkdownMessage({ content }: { content: string }) {
  return <div className="text-[13px] leading-7 wrap-anywhere text-slate-700 sm:text-sm [&_p]:mb-3 [&_p:last-child]:mb-0 [&_strong]:font-semibold [&_strong]:text-slate-900 [&_ul]:my-3 [&_ul]:list-disc [&_ul]:pl-5 [&_ol]:my-3 [&_ol]:list-decimal [&_ol]:pl-5 [&_li]:my-1 [&_li>p]:mb-1 [&_h1]:mb-3 [&_h1]:text-xl [&_h1]:font-semibold [&_h2]:mb-3 [&_h2]:text-lg [&_h2]:font-semibold [&_h3]:mb-2 [&_h3]:font-semibold [&_blockquote]:my-3 [&_blockquote]:border-l-2 [&_blockquote]:border-indigo-200 [&_blockquote]:pl-4 [&_blockquote]:text-slate-500 [&_pre]:my-3 [&_pre]:overflow-x-auto [&_pre]:rounded-xl [&_pre]:bg-slate-100 [&_pre]:p-4 [&_code]:rounded [&_code]:bg-slate-100 [&_code]:px-1 [&_code]:py-0.5 [&_code]:font-mono [&_code]:text-xs [&_pre_code]:p-0 [&_hr]:my-4 [&_hr]:border-slate-200 [&_table]:my-3 [&_table]:w-full [&_table]:text-left [&_th]:border-b [&_th]:border-slate-300 [&_th]:p-2 [&_td]:border-b [&_td]:border-slate-100 [&_td]:p-2">
    <Markdown skipHtml remarkPlugins={[remarkGfm]}
      allowedElements={['p', 'strong', 'em', 'ul', 'ol', 'li', 'blockquote', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'pre', 'code', 'a', 'br', 'hr', 'table', 'thead', 'tbody', 'tr', 'th', 'td', 'del']}
      components={{ a: ({ href, children }) => href
        ? <a href={href} target="_blank" rel="noopener noreferrer" className="text-indigo-600 underline decoration-indigo-200 underline-offset-2 hover:text-indigo-500">{children}</a>
        : <span>{children}</span> }}>
      {content}
    </Markdown>
  </div>
}
