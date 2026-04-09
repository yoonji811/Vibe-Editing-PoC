import { useCallback, useRef, useState } from 'react'

interface Props {
  onUpload: (file: File) => void
  isLoading: boolean
}

export default function ImageUploader({ onUpload, isLoading }: Props) {
  const [isDragging, setIsDragging] = useState(false)
  const inputRef = useRef<HTMLInputElement>(null)

  const handleFile = (file: File) => {
    if (!file.type.startsWith('image/')) return
    onUpload(file)
  }

  const onDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault()
      setIsDragging(false)
      const file = e.dataTransfer.files[0]
      if (file) handleFile(file)
    },
    [onUpload]
  )

  return (
    <div
      onClick={() => !isLoading && inputRef.current?.click()}
      onDragOver={(e) => { e.preventDefault(); setIsDragging(true) }}
      onDragLeave={() => setIsDragging(false)}
      onDrop={onDrop}
      className={`
        w-full max-w-2xl rounded-2xl cursor-pointer select-none transition-all
        flex flex-col items-center justify-center py-20 px-8
        ${isDragging ? 'bg-blue-50 border-2 border-dashed border-blue-300' : 'bg-gray-100 border-2 border-dashed border-gray-200 hover:border-gray-300'}
      `}
    >
      {isLoading ? (
        <div className="flex flex-col items-center gap-4">
          <div className="w-10 h-10 border-4 border-blue-500 border-t-transparent rounded-full animate-spin" />
          <p className="text-gray-500 text-sm">Uploading...</p>
        </div>
      ) : (
        <>
          <div className="w-12 h-12 bg-white rounded-xl shadow-sm flex items-center justify-center mb-6">
            <svg className="w-6 h-6 text-gray-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-8l-4-4m0 0L8 8m4-4v12" />
            </svg>
          </div>
          <h2 className="text-2xl font-bold text-gray-800">Drag &amp; Drop to Begin</h2>
          <p className="text-gray-500 text-sm mt-2 text-center">
            Drag your image here or{' '}
            <span className="text-blue-500 underline">browse files</span>{' '}
            to start your session
          </p>
          <div className="flex gap-2 mt-6">
            <span className="border border-gray-300 rounded-full px-3 py-1 text-xs text-gray-500 bg-white">RAW, JPG, PNG</span>
            <span className="border border-gray-300 rounded-full px-3 py-1 text-xs text-gray-500 bg-white">UP TO 50MB</span>
          </div>
        </>
      )}
      <input
        ref={inputRef}
        type="file"
        accept="image/*"
        capture="environment"
        className="hidden"
        onChange={(e) => {
          const file = e.target.files?.[0]
          if (file) handleFile(file)
        }}
      />
    </div>
  )
}
