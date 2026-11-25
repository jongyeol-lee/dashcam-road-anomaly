"""Windows Tk 편집기. 캔버스 표시 배율과 관계없이 초안에는 원본 좌표만 저장한다."""

import os
import tkinter as tk
from dataclasses import dataclass
from pathlib import Path
from tkinter import messagebox, ttk

import cv2
from PIL import Image, ImageTk

from scripts import annotate_dashcam_drafts as drafts
from scripts.diagnose_video_roi import shade_excluded


@dataclass(frozen=True)
class Viewport:
    crop: tuple[int, int, int, int]
    left: int
    top: int
    width: int
    height: int

    @classmethod
    def fit(cls, crop, width, height):
        x1, y1, x2, y2 = crop
        scale = min(width / (x2 - x1), height / (y2 - y1))
        w, h = max(1, round((x2 - x1) * scale)), max(1, round((y2 - y1) * scale))
        return cls(crop, (width - w) // 2, (height - h) // 2, w, h)

    def to_source(self, x, y):
        x1, y1, x2, y2 = self.crop
        return (x1 + round(min(1, max(0, (x - self.left) / self.width)) * (x2 - x1)),
                y1 + round(min(1, max(0, (y - self.top) / self.height)) * (y2 - y1)))

    def to_canvas(self, x, y):
        x1, y1, x2, y2 = self.crop
        return (self.left + (x - x1) * self.width / (x2 - x1),
                self.top + (y - y1) * self.height / (y2 - y1))


class DraftEditor:
    def __init__(self, window: tk.Tk, directory: Path):
        self.window, self.directory = window, directory
        background = directory.name == drafts.BACKGROUND_DIR
        self.ids = list(drafts.BACKGROUND_IDS if background else drafts.DETAIL_CROPS)
        self.index = 0
        self.selected = self.start = self.view = None
        self.coords = [tk.StringVar(window) for _ in range(4)]
        self.candidate = tk.StringVar(window, drafts.PENDING)
        self.status = tk.StringVar(window)
        self.zoom, self.roi = tk.BooleanVar(window), tk.BooleanVar(window)
        window.title("블랙박스 배경 후보 · 수동 검토" if background else "블랙박스 균열 후보 · 수동 박스 초안")
        width = min(1440, window.winfo_screenwidth() - 40)
        height = min(850, window.winfo_screenheight() - 90)
        window.geometry(f"{width}x{height}")
        window.columnconfigure(0, weight=1)
        window.rowconfigure(1, weight=1)

        nav = ttk.Frame(window, padding=(12, 8))
        nav.grid(row=0, column=0, columnspan=2, sticky="ew")
        self.previous = ttk.Button(nav, text="이전", command=lambda: self.navigate(-1))
        self.previous.pack(side="left")
        self.next = ttk.Button(nav, text="다음", command=lambda: self.navigate(1))
        self.next.pack(side="left", padx=5)
        self.title = ttk.Label(nav)
        self.title.pack(side="left", padx=10)
        ttk.Checkbutton(nav, text="ROI B 표시", variable=self.roi, command=self.redraw).pack(side="right")
        ttk.Checkbutton(nav, text="노면 확대", variable=self.zoom, command=self.redraw).pack(side="right", padx=10)

        self.canvas = tk.Canvas(window, width=400, height=300, bg="#202428", highlightthickness=0, cursor="crosshair")
        self.canvas.grid(row=1, column=0, sticky="nsew", padx=(12, 0))
        self.canvas.bind("<Configure>", lambda _: self.redraw())
        self.canvas.bind("<ButtonPress-1>", self.press)
        self.canvas.bind("<B1-Motion>", self.motion)
        self.canvas.bind("<ButtonRelease-1>", self.release)
        self.hint = ttk.Label(window, padding=(12, 8), wraplength=820)
        self.hint.grid(row=2, column=0, sticky="w")

        side = ttk.Frame(window, padding=(12, 0, 12, 8))
        side.grid(row=1, column=1, rowspan=2, sticky="nsew")
        ttk.Label(side, text="이 프레임의 박스").pack(anchor="w")
        self.box_list = tk.Listbox(side, width=42, height=6, exportselection=False)
        self.box_list.pack(fill="x", pady=(4, 6))
        self.box_list.bind("<<ListboxSelect>>", self.choose)
        row = ttk.Frame(side)
        row.pack(fill="x")
        ttk.Button(row, text="새 박스", command=self.reset_form).pack(side="left")
        ttk.Button(row, text="선택 삭제", command=self.delete).pack(side="left", padx=4)
        self.mode = ttk.Label(side)
        self.mode.pack(anchor="w", pady=(12, 4))
        ttk.Combobox(side, values=drafts.CANDIDATES, state="readonly", textvariable=self.candidate).pack(fill="x")
        coords = ttk.Frame(side)
        coords.pack(fill="x", pady=6)
        for i, (name, var) in enumerate(zip(("x1", "y1", "x2", "y2"), self.coords, strict=True)):
            ttk.Label(coords, text=name).grid(row=0, column=i, sticky="w")
            ttk.Entry(coords, textvariable=var, width=8).grid(row=1, column=i, padx=(0, 4))
        row = ttk.Frame(side)
        row.pack(fill="x")
        ttk.Button(row, text="박스 적용", command=self.apply).pack(side="left")
        ttk.Button(row, text="입력 취소", command=self.reset_form).pack(side="left", padx=4)
        self.stats = ttk.Label(side, wraplength=300)
        self.stats.pack(anchor="w", pady=6)
        ttk.Separator(side).pack(fill="x", pady=6)
        ttk.Label(side, text="이미지 검토 상태").pack(anchor="w")
        statuses = (*drafts.STATUSES, drafts.NO_DAMAGE) if background else drafts.STATUSES
        ttk.Combobox(side, values=statuses, state="readonly", textvariable=self.status).pack(fill="x")
        ttk.Label(side, text="메모 · 판단 근거와 같은 대상으로 보이는 프레임").pack(anchor="w", pady=(8, 2))
        self.notes = tk.Text(side, height=4, width=35, wrap="word", undo=True)
        self.notes.pack(fill="x")
        row = ttk.Frame(side)
        row.pack(fill="x", pady=8)
        ttk.Button(row, text="초안 저장", command=self.save).pack(side="left")
        ttk.Button(row, text="다시 열기", command=self.reload).pack(side="left", padx=4)
        ttk.Button(side, text="저장된 원본 · ROI 비교 열기", command=self.open_comparison).pack(anchor="w")
        window.protocol("WM_DELETE_WINDOW", self.close)
        self.load(0)

    def load(self, index):
        record, image = drafts.load_latest(self.directory, self.ids[index])
        self.index, self.record, self.image = index, record, image
        self.boxes = list(record["boxes"])
        self.status.set(record["review_status"])
        self.notes.delete("1.0", "end")
        self.notes.insert("1.0", record["user_notes"])
        self.title.configure(text=f"{index + 1} / {len(self.ids)}    {record['image_id']}    "
                             f"프레임 {record['frame_index']} · {record['estimated_time_sec']:.1f}초    "
                             f"초안 v{record['revision']:04d}")
        self.previous.state(["disabled"] if index == 0 else ["!disabled"])
        self.next.state(["disabled"] if index == len(self.ids) - 1 else ["!disabled"])
        self.refresh_list()
        self.reset_form()

    def refresh_list(self):
        self.box_list.delete(0, "end")
        for i, box in enumerate(self.boxes, 1):
            self.box_list.insert("end", f"{i}. {box['candidate_class']}   {tuple(box['xyxy'])}")

    def set_form(self, candidate, coords):
        self.candidate.set(candidate)
        for var, value in zip(self.coords, coords, strict=True):
            var.set(value)

    def reset_form(self):
        self.selected = self.start = None
        self.box_list.selection_clear(0, "end")
        self.set_form(drafts.PENDING, [""] * 4)
        self.mode.configure(text="새 박스 · 클래스 후보")
        self.stats.configure(text="박스를 선택하면 ROI B 판정이 표시됩니다.")
        self.hint.configure(text="원본이나 확대 화면에서 드래그한 뒤 클래스 후보를 선택하고 ‘박스 적용’을 누르세요.")
        self.redraw()

    def choose(self, _=None):
        selection = self.box_list.curselection()
        if selection:
            self.selected = selection[0]
            box = self.boxes[self.selected]
            self.set_form(box["candidate_class"], box["xyxy"])
            self.mode.configure(text=f"{self.selected + 1}번 박스 수정 · 클래스 후보")
            roi = box["roi_b"]
            self.stats.configure(text=f"중심 {'내부 · 유지' if roi['center_inside'] else '외부 · 제외'}  /  "
                                 f"경계 접촉·교차 {'있음' if roi['touches_boundary'] else '없음'}\n"
                                 f"제외 영역 면적 {roi['outside_area_fraction']:.1%}")
            self.canvas.delete("pending")

    def redraw(self):
        if not hasattr(self, "image"):
            return
        self.start = None
        crop = tuple(self.record["detail_crop_xyxy"]) if self.zoom.get() else (0, 0, *drafts.SIZE)
        self.view = Viewport.fit(crop, max(1, self.canvas.winfo_width()), max(1, self.canvas.winfo_height()))
        image = shade_excluded(self.image, drafts.ROI_B) if self.roi.get() else self.image.copy()
        drafts.paint_boxes(image, self.boxes)
        x1, y1, x2, y2 = crop
        tile = Image.fromarray(cv2.cvtColor(image[y1:y2, x1:x2], cv2.COLOR_BGR2RGB))
        sampling = Image.Resampling.NEAREST if self.view.width >= tile.width else Image.Resampling.BOX
        self.photo = ImageTk.PhotoImage(tile.resize((self.view.width, self.view.height), sampling))
        self.canvas.delete("all")
        self.canvas.create_image(self.view.left, self.view.top, image=self.photo, anchor="nw")

    def press(self, event):
        view = self.view
        if view.left <= event.x <= view.left + view.width and view.top <= event.y <= view.top + view.height:
            self.start = view.to_source(event.x, event.y)
            self.canvas.delete("pending")

    def motion(self, event):
        if self.start is not None:
            self.canvas.delete("pending")
            end = self.view.to_source(event.x, event.y)
            self.canvas.create_rectangle(*self.view.to_canvas(*self.start), *self.view.to_canvas(*end),
                                         tags="pending", outline="white", width=2, dash=(4, 3))

    def release(self, event):
        if self.start is None:
            return
        self.motion(event)
        x, y = self.start
        u, v = self.view.to_source(event.x, event.y)
        self.start = None
        if x != u and y != v:
            self.set_form(self.candidate.get(), (min(x, u), min(y, v), max(x, u), max(y, v)))
        else:
            self.canvas.delete("pending")

    def apply(self):
        try:
            values = [int(var.get()) for var in self.coords]
        except ValueError:
            return self.error("원본 좌표 네 개를 정수로 입력하거나 이미지에서 드래그하세요.")
        try:
            box = drafts.make_box(self.candidate.get(), values)
        except ValueError as exc:
            return self.error(str(exc))
        if self.selected is None:
            self.boxes.append(box)
        else:
            self.boxes[self.selected] = box
        self.refresh_list()
        self.reset_form()
        self.hint.configure(text="박스를 적용했습니다. 목록을 선택해 수정하거나 이미지 검토 상태와 메모를 저장하세요.")

    def delete(self):
        if self.selected is not None:
            self.boxes.pop(self.selected)
            self.refresh_list()
            self.reset_form()

    def pending_form(self):
        values = [v.get().strip() for v in self.coords]
        if self.selected is None:
            return any(values)
        box = self.boxes[self.selected]
        return self.candidate.get() != box["candidate_class"] or values != list(map(str, box["xyxy"]))

    def dirty(self):
        return (self.pending_form() or self.boxes != self.record["boxes"] or self.status.get() != self.record["review_status"]
                or self.notes.get("1.0", "end-1c") != self.record["user_notes"])

    def error(self, text):
        messagebox.showerror("박스 초안", text, parent=self.window)
        return False

    def save(self):
        if self.pending_form():
            return self.error("입력 중인 박스에 ‘박스 적용’ 또는 ‘입력 취소’를 먼저 누르세요.")
        if not self.dirty():
            self.hint.configure(text="저장할 변경이 없습니다.")
            return True
        record = {**self.record, "boxes": self.boxes, "review_status": self.status.get(),
                  "user_notes": self.notes.get("1.0", "end-1c")}
        try:
            drafts.save_revision(self.directory, self.image, record)
            self.load(self.index)
        except (OSError, ValueError) as exc:
            return self.error(str(exc))
        self.hint.configure(text="초안과 해당 버전의 원본 · ROI 박스 비교 이미지를 저장했습니다.")
        return True

    def can_leave(self):
        if not self.dirty():
            return True
        answer = messagebox.askyesnocancel("초안 변경", "이 이미지의 변경을 저장할까요?", parent=self.window)
        return answer is False or (answer is True and self.save())

    def navigate(self, step):
        index = self.index + step
        if 0 <= index < len(self.ids) and self.can_leave():
            self.load(index)

    def reload(self):
        if not self.dirty() or messagebox.askyesno("최신 버전", "현재 편집을 취소하고 최신 저장본을 열까요?", parent=self.window):
            self.load(self.index)

    def open_comparison(self):
        path = drafts.revision_dir(self.directory, self.record["image_id"], self.record["revision"])
        try:
            os.startfile(path / "roi_comparison.jpg")
        except OSError as exc:
            self.error(str(exc))

    def close(self):
        if self.can_leave():
            self.window.destroy()


def run_editor(directory: Path):
    window = tk.Tk()
    DraftEditor(window, directory)
    window.mainloop()
