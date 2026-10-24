import ClipThatCore
import SwiftUI

struct SidebarView: View {
    @EnvironmentObject private var model: AppModel
    @State private var renaming: Session?
    @State private var newTitle = ""
    @State private var confirmDelete: Session?

    var body: some View {
        List(selection: $model.selectedSessionID) {
            Section("Sessions") {
                ForEach(model.sessions) { session in
                    VStack(alignment: .leading, spacing: 2) {
                        Text(session.title)
                            .lineLimit(1)
                        Text(subtitle(for: session))
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    }
                    .padding(.vertical, 2)
                    .tag(session.id)
                    .contextMenu {
                        Button("Rename…") {
                            newTitle = session.title
                            renaming = session
                        }
                        Button("Show in Finder") {
                            model.reveal(model.fileURL("session.json", in: session))
                        }
                        Divider()
                        Button("Move to Trash…", role: .destructive) { confirmDelete = session }
                    }
                }
            }
        }
        .listStyle(.sidebar)
        .safeAreaInset(edge: .bottom) {
            HStack {
                Button {
                    model.newSession()
                } label: {
                    Label("New Session", systemImage: "plus")
                }
                .buttonStyle(.borderless)
                Spacer()
                Button {
                    model.revealLibrary()
                } label: {
                    Image(systemName: "folder")
                }
                .buttonStyle(.borderless)
                .help("Show the Clip That library in Finder")
            }
            .padding(10)
        }
        .alert("Rename Session", isPresented: Binding(get: { renaming != nil }, set: { if !$0 { renaming = nil } })) {
            TextField("Title", text: $newTitle)
            Button("Rename") {
                if let renaming { model.rename(renaming.id, to: newTitle) }
                renaming = nil
            }
            Button("Cancel", role: .cancel) { renaming = nil }
        }
        .confirmationDialog("Move “\(confirmDelete?.title ?? "")” to the Trash?",
                            isPresented: Binding(get: { confirmDelete != nil }, set: { if !$0 { confirmDelete = nil } })) {
            Button("Move to Trash", role: .destructive) {
                if let confirmDelete { model.deleteSession(confirmDelete.id) }
                confirmDelete = nil
            }
        } message: {
            Text("The session folder, its clips and renders go to the Trash. You can restore them from there.")
        }
    }

    private func subtitle(for session: Session) -> String {
        let count = session.clips.count
        let clips = count == 1 ? "1 clip" : "\(count) clips"
        return count == 0 ? "Empty" : "\(clips) · \(DurationFormat.clock(session.totalSelectedSeconds))"
    }
}
