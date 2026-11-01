"""Session-owned Playlist drafts over the shared semantic Library Workspace."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
from enum import StrEnum
from uuid import uuid4

from iOpenPod.app.library_workspace import LibraryWorkspace
from iOpenPod.app.smart_playlist_preview import preview_smart_playlist
from iPodDB.library import LibrarySnapshot, Playlist, Track
from iPodDB.library.playlists import PlaylistKind, PlaylistSortOrder, SmartPlaylist
from iPodDB.library.smart_rules import (
    smart_playlist_references,
    validate_smart_playlist,
)


class PlaylistAction(StrEnum):
    CREATE = "create"
    UPDATE = "update"
    MOVE = "move"
    DELETE = "delete"
    APPEND = "append"
    REMOVE_ENTRIES = "remove_entries"
    MOVE_ENTRIES_UP = "move_entries_up"
    MOVE_ENTRIES_DOWN = "move_entries_down"
    REORDER_ENTRIES = "reorder_entries"
    COPY_REGULAR = "copy_regular"
    EVALUATE = "evaluate"


@dataclass(frozen=True, slots=True)
class PlaylistEdit:
    """One atomic action; parent_id=None selects the root for create/move/copy."""

    action: PlaylistAction
    playlist_id: int | None = None
    name: str | None = None
    parent_id: int | None = None
    kind: PlaylistKind = PlaylistKind.PLAYLIST
    entry_ids: tuple[str, ...] = ()
    track_ids: tuple[int, ...] = ()
    sort_order: PlaylistSortOrder | None = None
    smart: SmartPlaylist | None = None
    description: str | None = None
    allow_repeat: bool = False


@dataclass(frozen=True, slots=True)
class PlaylistEditResult:
    playlist: Playlist | None
    skipped_duplicates: int = 0


class PlaylistDependencyError(ValueError):
    """A deletion would lose supported or uninterpretable rule dependencies."""

    def __init__(self, dependents: tuple[Playlist, ...]) -> None:
        self.dependent_ids = tuple(p.playlist_id for p in dependents)
        details = ", ".join(f"{p.name} ({p.playlist_id})" for p in dependents)
        super().__init__(
            f"Resolve Smart Playlist dependencies before deletion: {details}"
        )


class PlaylistSession:
    """An immutable desired-state history, independent of device persistence.

    Every operation is source/revision bound by the owning service and this opaque
    revision. Candidate Workspaces are private and adopted only on full success.
    Undo restores values, never a revision token or a previously allocated ID.
    """

    def __init__(self, snapshot: LibrarySnapshot) -> None:
        self._original = snapshot
        self._workspace = self._workspace_for(snapshot)
        self._history = [snapshot]
        self._cursor = 0
        self._identity = uuid4().hex
        self._revision = 0
        self._next_id = min((0, *(p.playlist_id for p in snapshot.playlists))) - 1
        self._locked = False

    @staticmethod
    def _workspace_for(snapshot: LibrarySnapshot) -> LibraryWorkspace:
        workspace = LibraryWorkspace()
        workspace.load(snapshot)
        return workspace

    @property
    def original_snapshot(self) -> LibrarySnapshot:
        return self._original

    @property
    def snapshot(self) -> LibrarySnapshot:
        return self._history[self._cursor]

    @property
    def revision(self) -> str:
        return f"{self._identity}:{self._revision}"

    @property
    def dirty(self) -> bool:
        return self.snapshot != self._original

    @property
    def can_undo(self) -> bool:
        return self._cursor > 0

    @property
    def can_redo(self) -> bool:
        return self._cursor + 1 < len(self._history)

    @property
    def locked(self) -> bool:
        return self._locked

    def set_locked(self, locked: bool) -> None:
        self._locked = locked

    def require_revision(self, expected_revision: str) -> None:
        if self._locked:
            raise ValueError("Wait for the current Playlist save to finish.")
        if expected_revision != self.revision:
            raise ValueError("The Playlist draft changed. Reload this action.")

    def playlist(self, playlist_id: int) -> Playlist:
        playlist = self._workspace.playlist(playlist_id)
        if playlist is None:
            raise ValueError("This Playlist is no longer in the Library.")
        return playlist

    def preview(
        self,
        smart: SmartPlaylist,
        *,
        playlist_id: int | None = None,
        now: int | None = None,
        checkpoint: Callable[[], None] = lambda: None,
    ) -> tuple[Track, ...]:
        """Compute proposed rules without altering saved membership or history."""
        if playlist_id is not None and playlist_id in smart_playlist_references(smart):
            raise ValueError("A Smart Playlist cannot reference itself.")
        return preview_smart_playlist(
            self.snapshot.tracks,
            smart,
            playlists=self.snapshot.playlists,
            now=now,
            checkpoint=checkpoint,
        )

    def deletion_impact(self, playlist_id: int) -> tuple[Playlist, ...]:
        """Return the complete iterative descendant closure for a deletion review."""
        self.playlist(playlist_id)
        removed = {playlist_id}
        pending = [playlist_id]
        while pending:
            current = pending.pop()
            for child in self._workspace.children_of(current):
                if child.playlist_id not in removed:
                    removed.add(child.playlist_id)
                    pending.append(child.playlist_id)
        return tuple(p for p in self.snapshot.playlists if p.playlist_id in removed)

    @staticmethod
    def _require_user_playlist(playlist: Playlist) -> None:
        if playlist.system_managed:
            raise ValueError(f'The Playlist "{playlist.name}" is managed by the iPod.')

    def _validate_deletion(self, playlist_id: int) -> None:
        removed = self.deletion_impact(playlist_id)
        for playlist in removed:
            self._require_user_playlist(playlist)
        removed_ids = {p.playlist_id for p in removed}
        dependents: list[Playlist] = []
        for playlist in self.snapshot.playlists:
            if playlist.playlist_id in removed_ids or playlist.smart is None:
                continue
            try:
                validate_smart_playlist(playlist.smart)
            except ValueError:
                # Unknown native conditions may reference any removed identity.
                dependents.append(playlist)
            else:
                if smart_playlist_references(playlist.smart) & removed_ids:
                    dependents.append(playlist)
        if dependents:
            raise PlaylistDependencyError(tuple(dependents))

    def edit(self, edit: PlaylistEdit, *, expected_revision: str) -> PlaylistEditResult:
        self.require_revision(expected_revision)
        if not isinstance(edit.action, PlaylistAction):
            raise ValueError("Choose a supported Playlist action.")
        if edit.name is not None:
            if not edit.name.strip() or "\0" in edit.name:
                raise ValueError("Enter a valid Playlist name.")
            edit.name.encode("utf-16-le")
        action = edit.action
        target = None
        if action is not PlaylistAction.CREATE:
            if edit.playlist_id is None:
                raise ValueError("Choose a Playlist for this action.")
            target = self.playlist(edit.playlist_id)
            self._require_user_playlist(target)
        if (
            action
            in (PlaylistAction.CREATE, PlaylistAction.MOVE, PlaylistAction.COPY_REGULAR)
            and edit.parent_id is not None
        ):
            self._require_user_playlist(self.playlist(edit.parent_id))
        candidate = self._workspace_for(self.snapshot)
        skipped = 0
        created = False
        result: Playlist | None
        if action is PlaylistAction.CREATE:
            result = candidate.create(
                edit.kind,
                edit.name or "",
                edit.parent_id,
                smart=edit.smart,
                description=edit.description or "",
                track_ids=edit.track_ids,
                sort_order=edit.sort_order,
            )
            created = True
        else:
            assert target is not None
            playlist_id = target.playlist_id
            if action is PlaylistAction.UPDATE:
                result = candidate.update(
                    playlist_id,
                    name=edit.name,
                    description=edit.description,
                    smart=edit.smart,
                    sort_order=edit.sort_order,
                )
            elif action is PlaylistAction.MOVE:
                candidate.move(playlist_id, edit.parent_id)
                result = candidate.playlist(playlist_id)
            elif action is PlaylistAction.DELETE:
                self._validate_deletion(playlist_id)
                candidate.remove_playlist(playlist_id, candidate.edit_revision)
                result = None
            elif action is PlaylistAction.APPEND:
                if target.kind is not PlaylistKind.PLAYLIST:
                    raise ValueError("Only regular Playlists allow membership edits.")
                added: list[int] = []
                seen = set(target.track_ids)
                for track_id in edit.track_ids:
                    if candidate.track(track_id) is None:
                        raise ValueError(
                            "A selected Track is no longer in the Library."
                        )
                    if not edit.allow_repeat and track_id in seen:
                        skipped += 1
                    else:
                        added.append(track_id)
                        seen.add(track_id)
                result = (
                    candidate.set_tracks(playlist_id, (*target.track_ids, *added))
                    if added
                    else target
                )
            elif action in (
                PlaylistAction.REMOVE_ENTRIES,
                PlaylistAction.MOVE_ENTRIES_UP,
                PlaylistAction.MOVE_ENTRIES_DOWN,
            ):
                if len(set(edit.entry_ids)) != len(edit.entry_ids):
                    raise ValueError("Choose each Playlist Entry only once.")
                entry_action = {
                    PlaylistAction.REMOVE_ENTRIES: "remove",
                    PlaylistAction.MOVE_ENTRIES_UP: "up",
                    PlaylistAction.MOVE_ENTRIES_DOWN: "down",
                }[action]
                candidate.edit_entries(
                    playlist_id, edit.entry_ids, entry_action, candidate.edit_revision
                )
                result = candidate.playlist(playlist_id)
            elif action is PlaylistAction.REORDER_ENTRIES:
                if (
                    target.kind is not PlaylistKind.PLAYLIST
                    or edit.sort_order not in (None, PlaylistSortOrder.MANUAL)
                    or (
                        edit.sort_order is None
                        and target.sort_order
                        not in (PlaylistSortOrder.DEFAULT, PlaylistSortOrder.MANUAL)
                    )
                ):
                    raise ValueError(
                        "Only a complete Manual Playlist can be reordered."
                    )
                entries = {e.entry_id: e for e in target.entries}
                if (
                    len(edit.entry_ids) != len(entries)
                    or set(edit.entry_ids) != entries.keys()
                ):
                    raise ValueError(
                        "Reorder the complete set of exact Playlist Entries."
                    )
                result = replace(
                    target,
                    entries=tuple(entries[i] for i in edit.entry_ids),
                    sort_order=(
                        target.sort_order
                        if edit.sort_order is None
                        else edit.sort_order
                    ),
                )
                candidate.load(
                    replace(
                        self.snapshot,
                        playlists=tuple(
                            result if p.playlist_id == playlist_id else p
                            for p in self.snapshot.playlists
                        ),
                    )
                )
            elif action is PlaylistAction.COPY_REGULAR:
                if target.kind is PlaylistKind.FOLDER:
                    raise ValueError(
                        "Choose a Playlist, not a Playlist Folder, to copy."
                    )
                result = candidate.create(
                    PlaylistKind.PLAYLIST,
                    edit.name or f"{target.name} copy",
                    edit.parent_id,
                    track_ids=target.track_ids,
                    sort_order=(
                        PlaylistSortOrder.MANUAL
                        if edit.sort_order is None
                        else edit.sort_order
                    ),
                )
                created = True
            else:
                result = candidate.evaluate_smart(playlist_id)
        desired = candidate.desired_snapshot()
        if created:
            assert result is not None
            old_id = result.playlist_id
            result = replace(result, playlist_id=self._next_id)
            desired = replace(
                desired,
                playlists=tuple(
                    result if p.playlist_id == old_id else p for p in desired.playlists
                ),
            )
            if (
                result.smart is not None
                and result.playlist_id in smart_playlist_references(result.smart)
            ):
                raise ValueError("A Smart Playlist cannot reference itself.")
        if desired != self.snapshot:
            self._workspace = self._workspace_for(desired)
            self._history[self._cursor + 1 :] = [desired]
            self._cursor += 1
            self._revision += 1
            if created:
                self._next_id -= 1
        return PlaylistEditResult(result, skipped)

    def undo(self, *, expected_revision: str) -> None:
        self.require_revision(expected_revision)
        if not self.can_undo:
            raise ValueError("There are no Playlist edits to undo.")
        self._cursor -= 1
        self._workspace = self._workspace_for(self.snapshot)
        self._revision += 1

    def redo(self, *, expected_revision: str) -> None:
        self.require_revision(expected_revision)
        if not self.can_redo:
            raise ValueError("There are no Playlist edits to redo.")
        self._cursor += 1
        self._workspace = self._workspace_for(self.snapshot)
        self._revision += 1

    def discard(self, *, expected_revision: str) -> None:
        self.require_revision(expected_revision)
        self._history = [self._original]
        self._cursor = 0
        self._workspace = self._workspace_for(self._original)
        self._revision += 1
