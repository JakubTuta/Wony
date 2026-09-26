/** The pill above the nav, used for every fire-and-forget action — "Running
 *  Good night", "10 minute timer started" — since the panel has no chat
 *  transcript to show it in instead. */
export function Toast({ text }: { text: string }) {
  return (
    <div className="fade-up absolute left-1/2 -translate-x-1/2 z-30" style={{ bottom: 28 }}>
      <div className="bg-text text-panel px-[30px] py-[18px] rounded-[40px] text-[21px] font-semibold whitespace-nowrap">
        {text}
      </div>
    </div>
  )
}
