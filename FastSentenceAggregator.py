import re
from pipecat.frames.frames import EndFrame, Frame, InterimTranscriptionFrame, TextFrame
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor


class FastSentenceAggregator(FrameProcessor):
    """自定义快速句子聚合器，遇到逗号等停顿符号立刻交给TTS发音"""

    def __init__(self):
        super().__init__()
        self._aggregation = ""

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)

        if isinstance(frame, InterimTranscriptionFrame):
            return

        if isinstance(frame, TextFrame):
            self._aggregation += frame.text
            if self._match_punctuation(self._aggregation):
                await self.push_frame(TextFrame(self._aggregation))
                self._aggregation = ""

        elif isinstance(frame, EndFrame):
            if self._aggregation:
                await self.push_frame(TextFrame(self._aggregation))
                self._aggregation = ""
            await self.push_frame(frame)
        else:
            await self.push_frame(frame, direction)

    def _match_punctuation(self, text: str) -> bool:
        pattern = r'[.?!。？！,，、;；\n]+[\'\"”’\]\)]*\s*$'
        return bool(re.search(pattern, text))
