import type { FolderItem } from '@/types'
import { del, get, patch, post } from './client'

/** 文件夹 CRUD（决策 21 / D8）：后端 backend/app/api/routes/folders.py。 */
export function listFolders() {
  return get<FolderItem[]>('/folders')
}

export function createFolder(name: string, parentId: number | null = null) {
  return post<FolderItem>('/folders', { name, parent_id: parentId })
}

export function renameFolder(folderId: number, name: string) {
  return patch<FolderItem>(`/folders/${folderId}`, { name })
}

export function deleteFolder(folderId: number) {
  return del<null>(`/folders/${folderId}`)
}
