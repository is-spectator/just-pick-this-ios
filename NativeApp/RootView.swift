import SwiftUI

enum AppRoute: Hashable {
    case resultDatong
    case askKorea
    case answer
}

struct RootView: View {
    @State private var path: [AppRoute]
    @State private var session: AppSession
    @State private var answerPollTask: Task<Void, Never>?

    init() {
        let demoScreen = DocumentationDemoScreen.current
        let session = AppSession(service: BackendRecommendationService(), documentationDemo: demoScreen?.rawValue)

        _session = State(initialValue: session)
        _path = State(initialValue: demoScreen?.initialPath ?? [])
    }

    var body: some View {
        NavigationStack(path: $path) {
            InputScreen(session: session) { decision in
                switch decision {
                case .top1:
                    path.append(.resultDatong)
                case .ask:
                    path.append(.askKorea)
                }
            } onAnswerEntry: {
                path.append(.answer)
            } onHistorySelect: { item in
                Task { @MainActor in
                    let destination = await session.restoreHistoryItem(item)
                    path.removeAll()
                    switch destination {
                    case .result:
                        path.append(.resultDatong)
                    case .ask:
                        path.append(.askKorea)
                    }
                }
            }
            .navigationDestination(for: AppRoute.self) { route in
                switch route {
                case .resultDatong:
                    ResultScreen(
                        session: session,
                        onAskHuman: {
                            session.makeHelpRequestFromCurrentTopPick()
                            path.append(.askKorea)
                        },
                        onDecision: { decision in
                            if case .ask = decision {
                                path.append(.askKorea)
                            }
                        },
                        onAccepted: { path.removeAll() },
                        onBackHome: { path.removeAll() }
                    )
                case .askKorea:
                    AskScreen(
                        session: session,
                        onHome: { path.removeAll() }
                    )
                case .answer:
                    AnswerScreen(session: session)
                }
            }
        }
        .tint(AppTheme.text)
        .onAppear {
            startAnswerPolling()
        }
        .onDisappear {
            answerPollTask?.cancel()
        }
    }

    private func startAnswerPolling() {
        answerPollTask?.cancel()
        answerPollTask = Task { @MainActor in
            while !Task.isCancelled {
                try? await Task.sleep(for: .seconds(3))
                guard !Task.isCancelled else { return }
                guard path.last != .askKorea else { continue }
                let hasNewAnswer = await session.refreshCurrentHelpRequest()
                if hasNewAnswer {
                    path.append(.askKorea)
                }
            }
        }
    }
}

private enum DocumentationDemoScreen: String {
    case result
    case ask
    case answer

    static var current: DocumentationDemoScreen? {
        #if DEBUG
        let prefix = "--demo-screen="
        guard let argument = ProcessInfo.processInfo.arguments.first(where: { $0.hasPrefix(prefix) }) else {
            return nil
        }

        return DocumentationDemoScreen(rawValue: String(argument.dropFirst(prefix.count)))
        #else
        return nil
        #endif
    }

    var initialPath: [AppRoute] {
        switch self {
        case .result:
            [.resultDatong]
        case .ask:
            [.askKorea]
        case .answer:
            [.answer]
        }
    }
}

#Preview {
    RootView()
}
