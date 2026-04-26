interface Props {
  imageSrc: string   // data URI (base64) or Cloudinary URL
  isLoading?: boolean
  showScrollHint?: boolean
  onMouseDown?: () => void
  onMouseUp?: () => void
  onMouseLeave?: () => void
}

export default function ImageViewer({
  imageSrc,
  isLoading,
  showScrollHint,
  onMouseDown,
  onMouseUp,
  onMouseLeave,
}: Props) {
  return (
    <div
      className="relative w-full flex items-center justify-center bg-gray-100 rounded-2xl overflow-hidden cursor-pointer select-none"
      style={{ height: '100%', maxHeight: '100%' }}
      onMouseDown={onMouseDown}
      onMouseUp={onMouseUp}
      onMouseLeave={onMouseLeave}
    >
      <img
        src={imageSrc}
        alt="편집 이미지"
        className={`max-w-full max-h-full object-contain pointer-events-none transition-opacity duration-200 ${isLoading ? 'opacity-40' : 'opacity-100'}`}
        style={{ maxHeight: '100%' }}
        draggable={false}
      />

      {isLoading && (
        <div className="absolute inset-0 flex flex-col items-center justify-center gap-3 pointer-events-none">
          <div className="w-10 h-10 border-4 border-blue-500 border-t-transparent rounded-full animate-spin" />
          <span className="text-sm text-gray-700 font-medium bg-white/70 px-3 py-1 rounded-full">
            편집 중...
          </span>
        </div>
      )}

      {showScrollHint && !isLoading && (
        <div className="absolute bottom-4 left-1/2 -translate-x-1/2 bg-black/50 text-white text-xs px-3 py-1.5 rounded-full pointer-events-none whitespace-nowrap">
          Scroll / swipe to view previous edits
        </div>
      )}
    </div>
  )
}
