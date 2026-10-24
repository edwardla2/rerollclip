import ClipThatCore
import SwiftUI

struct ContentView: View {
    @EnvironmentObject private var model: AppModel

    var body: some View {
        NavigationSplitView {
            SidebarView()
                .navigationSplitViewColumnWidth(min: 220, ideal: 250, max: 320)
        } detail: {
            VStack(spacing: 0) {
                CaptureBar()
                Divider()
                if let session = model.selectedSession {
                    SessionDetailView(session: session)
                        .id(session.id)
                } else {
                    EmptyLibraryView()
                }
            }
        }
        .overlay(alignment: .bottom) {
            if let banner = model.banner {
                BannerView(banner: banner)
                    .padding(.bottom, 84)
                    .transition(.move(edge: .bottom).combined(with: .opacity))
            }
        }
        .animation(.easeOut(duration: 0.2), value: model.banner)
    }
}

struct EmptyLibraryView: View {
    @EnvironmentObject private var model: AppModel

    var body: some View {
        VStack(spacing: 14) {
            Image(systemName: "film.stack")
                .font(.system(size: 40, weight: .light))
                .foregroundStyle(.secondary)
            Text("No session selected")
                .font(.title3.weight(.semibold))
            Text("A session collects the moments you want in one montage.")
                .foregroundStyle(.secondary)
            Button("New Session") { model.newSession() }
                .buttonStyle(.borderedProminent)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
    }
}

struct BannerView: View {
    @EnvironmentObject private var model: AppModel
    let banner: Banner

    var body: some View {
        HStack(spacing: 10) {
            Image(systemName: banner.isError ? "exclamationmark.triangle.fill" : "checkmark.circle.fill")
                .foregroundStyle(banner.isError ? Color.orange : Color.green)
            Text(banner.text)
                .lineLimit(3)
                .fixedSize(horizontal: false, vertical: true)
            Button {
                model.dismissBanner()
            } label: {
                Image(systemName: "xmark")
            }
            .buttonStyle(.plain)
            .foregroundStyle(.secondary)
        }
        .padding(.horizontal, 14)
        .padding(.vertical, 10)
        .frame(maxWidth: 560)
        .background(.regularMaterial, in: RoundedRectangle(cornerRadius: 10))
        .shadow(color: .black.opacity(0.15), radius: 8, y: 2)
    }
}
