import type { HistoryEntry } from '../hooks/useSession'

interface Props {
  history: HistoryEntry[]
  currentIndex: number
  onSelect: (index: number) => void
  onNewImage: () => void
}

function formatTime(iso: string): string {
  return new Date(iso).toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit', hour12: false })
}

export default function HistoryBar({ history, currentIndex, onSelect, onNewImage }: Props) {
  return (
    <div className="flex flex-col h-full">
      <div className="px-4 pt-5 pb-3 shrink-0">
        <p className="text-xs font-bold text-gray-800 uppercase tracking-widest">Recent States</p>
        <p className="text-xs text-gray-400 mt-0.5">Edit Timeline</p>
      </div>

      <div className="flex-1 overflow-y-auto px-3 space-y-3 min-h-0">
        {history.map((entry, i) => {
          const isActive = i === currentIndex
          const isLatest = i === history.length - 1
          const label = isLatest && i > 0 ? 'Current Session' : entry.label
          return (
            <button key={i} onClick={() => onSelect(i)} className="w-full text-left">
              <div className={`rounded-lg overflow-hidden border-2 transition-all ${
                isActive ? 'border-blue-400' : 'border-transparent hover:border-gray-300'
              }`}>
                <img
                  src={`data:image/jpeg;base64,${entry.imageB64}`}
                  alt={label}
                  className="w-full h-24 object-cover"
                />
              </div>
              <div className="mt-1 px-0.5">
                <p className={`text-xs font-medium truncate ${isActive && isLatest ? 'text-blue-500' : 'text-gray-700'}`}>
                  {label}
                </p>
                <p className="text-xs text-gray-400">{formatTime(entry.timestamp)}</p>
              </div>
            </button>
          )
        })}
      </div>

      <div className="p-4 border-t border-gray-200 shrink-0">
        <button
          onClick={onNewImage}
          className="flex items-center gap-1.5 text-xs text-blue-500 hover:text-blue-700 font-medium"
        >
          <span className="w-3 h-3 rounded-full bg-blue-500 inline-block" />
          History
        </button>
      </div>
    </div>
  )
}
