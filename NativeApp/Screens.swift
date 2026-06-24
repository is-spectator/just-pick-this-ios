import SwiftUI
import UIKit

private enum ChatEntry: Identifiable {
    case intro(UUID)
    case user(UUID, String)
    case notice(UUID, ServiceNotice)
    case recommendation(UUID, TopPick)
    case help(UUID, HelpRequest)

    var id: UUID {
        switch self {
        case .intro(let id),
             .user(let id, _),
             .notice(let id, _),
             .recommendation(let id, _),
             .help(let id, _):
            id
        }
    }

    var helpRequestId: UUID? {
        if case .help(_, let request) = self {
            return request.id
        }
        return nil
    }
}

struct InputScreen: View {
    let session: AppSession
    let onDecision: (RecommendationDecision) -> Void
    let onMenu: () -> Void
    let onHistorySelect: (QuestionHistory) -> Void

    @State private var draft = ""
    @State private var entries: [ChatEntry] = [.intro(UUID())]
    @State private var submitTask: Task<Void, Never>?
    @State private var toastTask: Task<Void, Never>?
    @State private var isAcceptingPick = false
    @State private var isPublishingHelp = false
    @State private var showsNewConversationToast = false

    var body: some View {
        AppChrome(
            showsBack: false,
            backAction: nil,
            onHistory: onMenu,
            onNewConversation: startNewConversation
        ) {
            ScrollViewReader { proxy in
                ScrollView {
                    LazyVStack(alignment: .leading, spacing: 18) {
                        ForEach(entries) { entry in
                            row(for: entry)
                                .id(entry.id)
                        }

                        if session.isSubmitting {
                            AssistantThinkingRow()
                                .id("thinking")
                        }
                    }
                    .padding(.horizontal, 18)
                    .padding(.top, 14)
                    .padding(.bottom, 20)
                    .contentShape(Rectangle())
                    .onTapGesture {
                        dismissKeyboard()
                    }
                }
                .scrollIndicators(.hidden)
                .scrollDismissesKeyboard(.interactively)
                .onChange(of: entries.count) { _, _ in
                    scrollToBottom(with: proxy)
                }
                .onChange(of: session.isSubmitting) { _, _ in
                    scrollToBottom(with: proxy)
                }
            }
        } footer: {
            BottomComposer(
                text: $draft,
                placeholder: MockData.queryPlaceholder,
                isSending: session.isSubmitting
            ) {
                submit()
            }
        }
        .onDisappear {
            submitTask?.cancel()
            toastTask?.cancel()
        }
        .overlay(alignment: .top) {
            if showsNewConversationToast {
                Text("已开启新对话")
                    .font(.system(size: 14, weight: .semibold))
                    .foregroundStyle(.white)
                    .padding(.horizontal, 14)
                    .frame(height: 36)
                    .background(AppTheme.text)
                    .clipShape(Capsule())
                    .padding(.top, 8)
                    .transition(.opacity.combined(with: .move(edge: .top)))
            }
        }
        .animation(.easeOut(duration: 0.18), value: session.isSubmitting)
    }

    @ViewBuilder
    private func row(for entry: ChatEntry) -> some View {
        switch entry {
        case .intro:
            AssistantIntroRow()
        case .user(_, let text):
            UserChatBubble(text: text)
        case .notice(_, let notice):
            AssistantNoticeRow(notice: notice)
        case .recommendation(_, let pick):
            AssistantRecommendationRow(
                pick: pick,
                isAccepting: isAcceptingPick,
                onAskHuman: makeHelpRequestFromPick,
                onAccept: acceptPick
            )
        case .help(_, let request):
            AssistantHelpRow(
                request: request,
                isPublishing: isPublishingHelp,
                onPublish: { publish(request) }
            )
        }
    }

    private func submit() {
        let query = draft.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !query.isEmpty, !session.isSubmitting else { return }

        dismissKeyboard()
        draft = ""
        entries.append(.user(UUID(), query))
        submitTask?.cancel()
        submitTask = Task { @MainActor in
            let decision = await session.submit(query: query)
            guard !Task.isCancelled else { return }
            appendAssistantResponse(for: decision)
        }
    }

    private func appendAssistantResponse(for decision: RecommendationDecision) {
        switch decision {
        case .none:
            if let notice = session.serviceNotice {
                entries.append(.notice(UUID(), notice))
            }
        case .top1(let pick):
            entries.append(.recommendation(UUID(), pick))
        case .ask(let request):
            entries.append(.help(UUID(), request))
        }
    }

    private func makeHelpRequestFromPick() {
        dismissKeyboard()
        session.makeHelpRequestFromCurrentTopPick()
        entries.append(.help(UUID(), session.helpRequest))
    }

    private func acceptPick() {
        guard !isAcceptingPick else { return }
        dismissKeyboard()
        isAcceptingPick = true
        Task { @MainActor in
            await session.acceptCurrentTopPick()
            isAcceptingPick = false
            entries.append(.notice(UUID(), ServiceNotice(title: "皮皮", detail: "就这个。")))
        }
    }

    private func publish(_ request: HelpRequest) {
        guard request.status == .draft, !isPublishingHelp else { return }
        dismissKeyboard()
        isPublishingHelp = true
        Task { @MainActor in
            await session.publishCurrentRequest()
            if let updated = session.currentHelpRequest {
                updateHelpEntry(updated)
            }
            isPublishingHelp = false
            entries.append(.notice(UUID(), ServiceNotice(title: "皮皮", detail: "发出去了，等懂的人来一句。")))
        }
    }

    private func updateHelpEntry(_ request: HelpRequest) {
        guard let index = entries.firstIndex(where: { $0.helpRequestId == request.id }) else { return }
        entries[index] = .help(entries[index].id, request)
    }

    private func scrollToBottom(with proxy: ScrollViewProxy) {
        DispatchQueue.main.async {
            withAnimation(.easeOut(duration: 0.2)) {
                if session.isSubmitting {
                    proxy.scrollTo("thinking", anchor: .bottom)
                } else if let last = entries.last {
                    proxy.scrollTo(last.id, anchor: .bottom)
                }
            }
        }
    }

    private func startNewConversation() {
        submitTask?.cancel()
        dismissKeyboard()
        draft = ""
        session.startNewConversation()
        entries = [.intro(UUID())]
        showNewConversationToast()
    }

    private func showNewConversationToast() {
        toastTask?.cancel()
        withAnimation(.easeOut(duration: 0.18)) {
            showsNewConversationToast = true
        }
        toastTask = Task { @MainActor in
            try? await Task.sleep(nanoseconds: 1_400_000_000)
            guard !Task.isCancelled else { return }
            withAnimation(.easeOut(duration: 0.18)) {
                showsNewConversationToast = false
            }
        }
    }

    private func openHistoryItem(_ item: QuestionHistory) {
        submitTask?.cancel()
        dismissKeyboard()
        draft = ""
        onHistorySelect(item)
    }

    private func dismissKeyboard() {
        UIApplication.shared.sendAction(#selector(UIResponder.resignFirstResponder), to: nil, from: nil, for: nil)
    }
}

struct EmailLoginView: View {
    let authService: AuthAPIService
    let onDone: () -> Void

    @State private var email = AuthTokenStore.email ?? ""
    @State private var nickname = AuthTokenStore.displayName ?? ""
    @State private var code = ""
    @State private var codeSent = false
    @State private var isSubmitting = false
    @State private var message: String?

    var body: some View {
        NavigationStack {
            VStack(alignment: .leading, spacing: 18) {
                VStack(alignment: .leading, spacing: 8) {
                    Text(AuthTokenStore.email == nil ? "邮箱登录" : "账号")
                        .font(.system(size: 24, weight: .semibold))
                        .foregroundStyle(AppTheme.text)

                    if let signedInEmail = AuthTokenStore.email {
                        Text(signedInEmail)
                            .font(.system(size: 15))
                            .foregroundStyle(AppTheme.textSecondary)
                        if let displayName = AuthTokenStore.displayName, !displayName.isEmpty {
                            Text("昵称：\(displayName)")
                                .font(.system(size: 15, weight: .medium))
                                .foregroundStyle(AppTheme.text)
                        }
                    } else {
                        Text("用验证码登录，设备上的记录会绑定到这个邮箱。")
                            .font(.system(size: 14))
                            .lineSpacing(4)
                            .foregroundStyle(AppTheme.textSecondary)
                    }
                }

                if AuthTokenStore.email == nil {
                    TextField("邮箱", text: $email)
                        .textContentType(.emailAddress)
                        .keyboardType(.emailAddress)
                        .textInputAutocapitalization(.never)
                        .autocorrectionDisabled()
                        .padding(.horizontal, 14)
                        .frame(height: 48)
                        .background(AppTheme.card)
                        .clipShape(RoundedRectangle(cornerRadius: 14, style: .continuous))
                        .overlay(
                            RoundedRectangle(cornerRadius: 14, style: .continuous)
                                .stroke(AppTheme.border, lineWidth: 1)
                        )

                    if codeSent {
                        TextField("6 位验证码", text: $code)
                            .keyboardType(.numberPad)
                            .textContentType(.oneTimeCode)
                            .padding(.horizontal, 14)
                            .frame(height: 48)
                            .background(AppTheme.card)
                            .clipShape(RoundedRectangle(cornerRadius: 14, style: .continuous))
                            .overlay(
                                RoundedRectangle(cornerRadius: 14, style: .continuous)
                                    .stroke(AppTheme.border, lineWidth: 1)
                            )
                    }

                    Button {
                        submit()
                    } label: {
                        Text(codeSent ? "登录" : "获取验证码")
                            .font(.system(size: 17, weight: .semibold))
                            .frame(maxWidth: .infinity)
                            .frame(height: 50)
                            .foregroundStyle(.white)
                            .background(AppTheme.text)
                            .clipShape(Capsule())
                    }
                    .disabled(isSubmitting || email.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty || (codeSent && code.count < 6))
                    .opacity(isSubmitting ? 0.55 : 1)
                } else {
                    TextField("昵称", text: $nickname)
                        .textContentType(.nickname)
                        .textInputAutocapitalization(.never)
                        .autocorrectionDisabled()
                        .padding(.horizontal, 14)
                        .frame(height: 48)
                        .background(AppTheme.card)
                        .clipShape(RoundedRectangle(cornerRadius: 14, style: .continuous))
                        .overlay(
                            RoundedRectangle(cornerRadius: 14, style: .continuous)
                                .stroke(AppTheme.border, lineWidth: 1)
                        )

                    Button {
                        saveNickname()
                    } label: {
                        Text("保存昵称")
                            .font(.system(size: 17, weight: .semibold))
                            .frame(maxWidth: .infinity)
                            .frame(height: 50)
                            .foregroundStyle(.white)
                            .background(AppTheme.text)
                            .clipShape(Capsule())
                    }
                    .disabled(isSubmitting || nickname.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
                    .opacity(isSubmitting ? 0.55 : 1)

                    Button(role: .destructive) {
                        logout()
                    } label: {
                        Text("退出登录")
                            .font(.system(size: 17, weight: .semibold))
                            .frame(maxWidth: .infinity)
                            .frame(height: 50)
                    }
                    .buttonStyle(.bordered)
                }

                if let message {
                    Text(message)
                        .font(.system(size: 13))
                        .foregroundStyle(AppTheme.textSecondary)
                }

                Spacer()
            }
            .padding(22)
            .background(AppTheme.background)
            .navigationTitle("")
            .toolbar {
                ToolbarItem(placement: .topBarTrailing) {
                    Button("关闭") {
                        onDone()
                    }
                    .foregroundStyle(AppTheme.text)
                }
            }
        }
    }

    private func submit() {
        let trimmedEmail = email.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmedEmail.isEmpty, !isSubmitting else { return }
        isSubmitting = true
        message = nil
        Task { @MainActor in
            do {
                if codeSent {
                    let account = try await authService.verify(email: trimmedEmail, code: code)
                    nickname = account.displayName
                    message = "已登录。"
                    onDone()
                } else {
                    try await authService.requestCode(email: trimmedEmail)
                    codeSent = true
                    message = "验证码已发送。"
                }
            } catch {
                message = "没成功：\(error.localizedDescription)"
            }
            isSubmitting = false
        }
    }

    private func saveNickname() {
        let trimmedNickname = nickname.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmedNickname.isEmpty, !isSubmitting else { return }
        isSubmitting = true
        message = nil
        Task { @MainActor in
            do {
                let account = try await authService.updateDisplayName(trimmedNickname)
                nickname = account.displayName
                message = "昵称已保存。"
            } catch {
                message = "没成功：\(error.localizedDescription)"
            }
            isSubmitting = false
        }
    }

    private func logout() {
        isSubmitting = true
        Task { @MainActor in
            await authService.logout()
            email = ""
            nickname = ""
            code = ""
            codeSent = false
            isSubmitting = false
            message = "已退出。"
        }
    }
}

private struct AssistantAvatar: View {
    var body: some View {
        ZStack {
            Circle()
                .fill(AppTheme.card)
                .frame(width: 30, height: 30)
                .overlay(
                    Circle()
                        .stroke(AppTheme.border, lineWidth: 1)
                )

            Image(systemName: "sparkles")
                .font(.system(size: 13, weight: .semibold))
                .foregroundStyle(AppTheme.green)
        }
    }
}

private struct AssistantHeader: View {
    let name: String

    var body: some View {
        HStack(spacing: 10) {
            AssistantAvatar()

            Text(name)
                .font(.system(size: 15, weight: .medium))
                .foregroundStyle(AppTheme.textSecondary)
        }
    }
}

private struct AssistantIntroRow: View {
    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            AssistantHeader(name: "皮皮")

            Text("你在哪? 想做什么?")
                .font(.system(size: 17, weight: .medium))
                .lineSpacing(4)
                .foregroundStyle(AppTheme.text)
                .padding(.horizontal, 16)
                .padding(.vertical, 13)
                .background(AppTheme.card)
                .clipShape(RoundedRectangle(cornerRadius: 20, style: .continuous))
                .overlay(
                    RoundedRectangle(cornerRadius: 20, style: .continuous)
                        .stroke(AppTheme.border, lineWidth: 1)
                )
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }
}

private struct UserChatBubble: View {
    let text: String

    var body: some View {
        HStack {
            Spacer(minLength: 48)

            Text(text)
                .font(.system(size: 18))
                .lineSpacing(5)
                .foregroundStyle(AppTheme.text)
                .padding(.horizontal, 18)
                .padding(.vertical, 14)
                .background(AppTheme.bubble)
                .clipShape(RoundedRectangle(cornerRadius: 24, style: .continuous))
                .frame(maxWidth: 315, alignment: .trailing)
        }
        .frame(maxWidth: .infinity)
        .accessibilityElement(children: .combine)
        .accessibilityLabel("我, \(text)")
    }
}

private struct AssistantNoticeRow: View {
    let notice: ServiceNotice

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            AssistantHeader(name: notice.title)

            Text(notice.detail)
                .font(.system(size: 15))
                .lineSpacing(4)
                .foregroundStyle(AppTheme.text)
                .padding(.horizontal, 15)
                .padding(.vertical, 12)
                .background(AppTheme.card)
                .clipShape(RoundedRectangle(cornerRadius: 18, style: .continuous))
                .overlay(
                    RoundedRectangle(cornerRadius: 18, style: .continuous)
                        .stroke(AppTheme.border, lineWidth: 1)
                )
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .accessibilityElement(children: .combine)
        .accessibilityLabel("\(notice.title), \(notice.detail)")
    }
}

private struct AssistantThinkingRow: View {
    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            AssistantHeader(name: "皮皮")

            HStack(spacing: 9) {
                ProgressView()
                    .tint(AppTheme.textMuted)
                    .scaleEffect(0.82)

                Text("正在想一个...")
                    .font(.system(size: 14))
                    .foregroundStyle(AppTheme.textSecondary)
            }
            .padding(.horizontal, 15)
            .padding(.vertical, 12)
            .background(AppTheme.card)
            .clipShape(Capsule())
            .overlay(
                Capsule()
                    .stroke(AppTheme.border, lineWidth: 1)
            )
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }
}

private struct AssistantRecommendationRow: View {
    let pick: TopPick
    let isAccepting: Bool
    let onAskHuman: () -> Void
    let onAccept: () -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            AssistantHeader(name: "皮皮")
            ChatRecommendationCard(
                pick: pick,
                isAccepting: isAccepting,
                onAskHuman: onAskHuman,
                onAccept: onAccept
            )
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }
}

private struct AssistantHelpRow: View {
    let request: HelpRequest
    let isPublishing: Bool
    let onPublish: () -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            AssistantHeader(name: "皮皮")
            ChatHelpCard(request: request, isPublishing: isPublishing, onPublish: onPublish)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }
}

private struct ChatRecommendationCard: View {
    let pick: TopPick
    let isAccepting: Bool
    let onAskHuman: () -> Void
    let onAccept: () -> Void

    @State private var hasAppeared = false
    @State private var acceptFeedbackCount = 0

    private var imageURL: URL? {
        guard let url = pick.referenceImage?.url else { return nil }
        return URL(string: url)
    }

    private var decisionReason: String {
        let reason = pick.reason.trimmingCharacters(in: .whitespacesAndNewlines)
        if !reason.isEmpty {
            return reason
        }
        let subtitle = pick.subtitle.trimmingCharacters(in: .whitespacesAndNewlines)
        return subtitle.isEmpty ? "皮皮替你收成这一个。" : subtitle
    }

    private var supportingSubtitle: String? {
        let subtitle = pick.subtitle.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !subtitle.isEmpty, subtitle != decisionReason else { return nil }
        return subtitle
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 20) {
            if imageURL != nil {
                heroImage
            }

            VStack(alignment: .leading, spacing: 12) {
                if let supportingSubtitle {
                    Text(supportingSubtitle)
                        .font(.system(size: 15, weight: .medium))
                        .foregroundStyle(AppTheme.textSecondary)
                        .lineLimit(2)
                }

                Text(pick.title)
                    .font(.system(size: imageURL == nil ? 30 : 28, weight: .bold))
                    .lineSpacing(3)
                    .foregroundStyle(AppTheme.text)
                    .lineLimit(imageURL == nil ? 4 : 3)
                    .minimumScaleFactor(0.76)

                Text(decisionReason)
                    .font(.system(size: 18, weight: .medium))
                    .lineSpacing(5)
                    .foregroundStyle(AppTheme.textSecondary)
                    .lineLimit(3)
                    .fixedSize(horizontal: false, vertical: true)
            }

            HStack(spacing: 12) {
                Button(action: onAskHuman) {
                    Text("求一个")
                        .font(.system(size: 16, weight: .semibold))
                        .foregroundStyle(AppTheme.text)
                        .frame(maxWidth: .infinity)
                        .frame(height: 52)
                        .background(AppTheme.card)
                        .clipShape(Capsule())
                        .overlay(
                            Capsule()
                                .stroke(AppTheme.border, lineWidth: 1)
                        )
                }
                .buttonStyle(.plain)
                .accessibilityLabel("求一个")

                Button {
                    acceptFeedbackCount += 1
                    onAccept()
                } label: {
                    HStack(spacing: 8) {
                        if isAccepting {
                            ProgressView()
                                .tint(Color.white)
                                .scaleEffect(0.76)
                        }

                        Text(isAccepting ? "确认中" : "就这个")
                            .font(.system(size: 16, weight: .semibold))
                    }
                    .foregroundStyle(Color.white)
                    .frame(maxWidth: .infinity)
                    .frame(height: 52)
                    .background(AppTheme.text)
                    .clipShape(Capsule())
                    .animation(.spring(response: 0.22, dampingFraction: 0.88), value: isAccepting)
                }
                .buttonStyle(.plain)
                .disabled(isAccepting)
                .accessibilityLabel("就这个")
                .sensoryFeedback(.selection, trigger: acceptFeedbackCount)
            }
        }
        .padding(imageURL == nil ? 22 : 16)
        .padding(.bottom, 20)
        .frame(minHeight: imageURL == nil ? 270 : nil, alignment: .topLeading)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(AppTheme.card)
        .clipShape(RoundedRectangle(cornerRadius: 28, style: .continuous))
        .overlay(
            RoundedRectangle(cornerRadius: 28, style: .continuous)
                .stroke(AppTheme.border, lineWidth: 1)
        )
        .shadow(color: .black.opacity(0.055), radius: 22, x: 0, y: 12)
        .scaleEffect(hasAppeared ? 1 : 0.985)
        .opacity(hasAppeared ? 1 : 0)
        .offset(y: hasAppeared ? 0 : 8)
        .animation(.spring(response: 0.34, dampingFraction: 0.88), value: hasAppeared)
        .onAppear {
            hasAppeared = true
        }
        .accessibilityElement(children: .combine)
        .accessibilityLabel("推荐卡, \(pick.title), \(decisionReason)")
    }

    @ViewBuilder
    private var heroImage: some View {
        if let imageURL {
            AsyncImage(url: imageURL) { phase in
                switch phase {
                case .success(let image):
                    image
                        .resizable()
                        .scaledToFill()
                case .failure:
                    Color.clear
                case .empty:
                    ZStack {
                        AppTheme.bubble
                        ProgressView()
                            .tint(AppTheme.textMuted)
                    }
                @unknown default:
                    Color.clear
                }
            }
            .frame(maxWidth: .infinity)
            .frame(height: 228)
            .background(AppTheme.bubble)
            .clipShape(RoundedRectangle(cornerRadius: 22, style: .continuous))
            .accessibilityHidden(true)
        }
    }
}

private struct ChatHelpCard: View {
    let request: HelpRequest
    let isPublishing: Bool
    let onPublish: () -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: 15) {
            HStack(alignment: .center) {
                Text("求一个")
                    .font(.system(size: 12, weight: .medium))
                    .tracking(1.2)
                    .foregroundStyle(AppTheme.textMuted)

                Spacer()

                Text(request.status.label)
                    .font(.system(size: 12, weight: .medium))
                    .foregroundStyle(AppTheme.textMuted)
            }

            VStack(alignment: .leading, spacing: 9) {
                Text(request.title)
                    .font(.system(size: 23, weight: .semibold))
                    .lineSpacing(3)
                    .foregroundStyle(AppTheme.text)
                    .fixedSize(horizontal: false, vertical: true)

                Text(request.context)
                    .font(.system(size: 14))
                    .lineSpacing(4)
                    .foregroundStyle(AppTheme.textSecondary)
                    .fixedSize(horizontal: false, vertical: true)
            }

            if request.status == .draft {
                Button(action: onPublish) {
                    HStack(spacing: 8) {
                        if isPublishing {
                            ProgressView()
                                .tint(Color.white)
                                .scaleEffect(0.76)
                        }

                        Text(isPublishing ? "发出去中" : "发出去")
                            .font(.system(size: 15, weight: .medium))
                    }
                    .foregroundStyle(Color.white)
                    .frame(maxWidth: .infinity)
                    .frame(height: 50)
                    .background(AppTheme.text)
                    .clipShape(Capsule())
                }
                .buttonStyle(.plain)
                .disabled(isPublishing)
                .accessibilityLabel("发出去")
            } else {
                HStack(spacing: 8) {
                    Image(systemName: "paperplane")
                        .font(.system(size: 13, weight: .medium))

                    Text("已发出去")
                        .font(.system(size: 13, weight: .medium))
                }
                .foregroundStyle(AppTheme.textSecondary)
                .padding(.horizontal, 13)
                .padding(.vertical, 10)
                .background(AppTheme.bubble)
                .clipShape(Capsule())
            }
        }
        .padding(18)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(AppTheme.card)
        .clipShape(RoundedRectangle(cornerRadius: 22, style: .continuous))
        .overlay(
            RoundedRectangle(cornerRadius: 22, style: .continuous)
                .stroke(AppTheme.border, lineWidth: 1)
        )
        .shadow(color: .black.opacity(0.04), radius: 14, x: 0, y: 8)
        .accessibilityElement(children: .combine)
        .accessibilityLabel("求一个, \(request.title), \(request.context)")
    }
}

struct ResultScreen: View {
    let session: AppSession
    let onAskHuman: () -> Void
    let onDecision: (RecommendationDecision) -> Void
    let onAccepted: () -> Void
    let onBackHome: () -> Void

    @State private var draft = ""
    @State private var isFollowingUp = false
    @State private var isAccepting = false

    var body: some View {
        AppChrome(showsBack: true, backAction: onBackHome) {
            ScrollView {
                VStack(spacing: 0) {
                    QueryBubble(text: session.currentQuery.isEmpty ? MockData.queryPlaceholder : session.currentQuery)

                    if let notice = session.serviceNotice {
                        ServiceNoticePill(notice: notice)
                            .padding(.bottom, 12)
                    }

                    DecisionCard(
                        pick: session.topPick,
                        isFollowingUp: isFollowingUp,
                        isAccepting: isAccepting,
                        onFollowup: followUp,
                        onAskHuman: onAskHuman,
                        onReject: onAskHuman,
                        onAccept: accept
                    )
                }
                .padding(.horizontal, 16)
                .padding(.bottom, 18)
            }
            .scrollIndicators(.hidden)
        } footer: {
            BottomComposer(text: $draft, placeholder: "继续问一句", isSending: isFollowingUp) {
                submitDraftFollowup()
            }
        }
    }

    private func submitDraftFollowup() {
        let question = draft.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !question.isEmpty else { return }
        draft = ""
        followUp(question)
    }

    private func followUp(_ question: String) {
        guard !isFollowingUp, !isAccepting else { return }
        let baseQuery = session.currentQuery.isEmpty ? MockData.queryPlaceholder : session.currentQuery
        let followupQuery = "\(baseQuery)；\(question)"
        isFollowingUp = true
        Task { @MainActor in
            let decision = await session.submit(query: followupQuery)
            guard !Task.isCancelled else { return }
            isFollowingUp = false
            onDecision(decision)
        }
    }

    private func accept() {
        guard !isAccepting else { return }
        isAccepting = true
        Task { @MainActor in
            await session.acceptCurrentTopPick()
            isAccepting = false
            onAccepted()
        }
    }
}

struct AskScreen: View {
    let session: AppSession
    let onHome: () -> Void

    @State private var draft = ""
    @State private var isPublishing = false
    @State private var toastMessage = "发出去了，等别人来一句。"
    @State private var showsToast = false
    @State private var publishTask: Task<Void, Never>?
    @State private var pollTask: Task<Void, Never>?
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        AppChrome(showsBack: true, backAction: goBack) {
            ZStack {
                ScrollView {
                    VStack(spacing: 0) {
                        PageIntro(
                            title: session.helpRequest.answers.isEmpty ? "求一个" : "有人来一句了",
                            subtitle: session.helpRequest.answers.isEmpty
                                ? "这题我不硬选。\n我帮你发出去,等懂的人来一句。"
                                : "先看这一句,够用就别再刷了。"
                        )
                        if let notice = session.serviceNotice {
                            ServiceNoticePill(notice: notice)
                                .padding(.bottom, 16)
                        }
                        RequestCard(request: session.helpRequest)
                        if !session.helpRequest.answers.isEmpty {
                            PrimaryButton(title: "采纳这句") {
                                acceptAnswer()
                            }
                            .padding(.top, 20)
                        }
                        if session.helpRequest.status == .draft {
                            PrimaryButton(title: isPublishing ? "发出去中" : "发出去") {
                                publish()
                            }
                            .disabled(isPublishing)
                            .opacity(isPublishing ? 0.52 : 1)
                            .padding(.top, 20)
                        } else if session.helpRequest.answers.isEmpty {
                            PrimaryButton(title: "回首页") {
                                onHome()
                            }
                            .padding(.top, 20)
                        }
                    }
                    .padding(.horizontal, 16)
                    .padding(.bottom, 18)
                }
                .scrollIndicators(.hidden)

                ToastView(message: toastMessage, isVisible: showsToast)
            }
        } footer: {
            if session.helpRequest.status == .draft {
                BottomComposer(text: $draft, placeholder: "补一句背景", isSending: isPublishing) {
                    session.addHelpContext(draft)
                    draft = ""
                }
            } else {
                Color.clear
                    .frame(height: 20)
            }
        }
        .onAppear {
            startPolling()
        }
        .onDisappear {
            publishTask?.cancel()
            pollTask?.cancel()
        }
    }

    private func publish() {
        guard session.helpRequest.status == .draft, !isPublishing else { return }
        isPublishing = true
        publishTask?.cancel()
        publishTask = Task { @MainActor in
            await session.publishCurrentRequest()
            isPublishing = false
            toastMessage = "发出去了，等别人来一句。"
            showsToast = true
            try? await Task.sleep(for: .milliseconds(650))
            guard !Task.isCancelled else { return }
            showsToast = false
            onHome()
        }
    }

    private func goBack() {
        guard !isPublishing else { return }
        if session.helpRequest.status == .draft {
            dismiss()
        } else {
            onHome()
        }
    }

    private func startPolling() {
        pollTask?.cancel()
        pollTask = Task { @MainActor in
            while !Task.isCancelled {
                try? await Task.sleep(for: .seconds(2))
                guard !Task.isCancelled else { return }
                let hasNewAnswer = await session.refreshCurrentHelpRequest()
                if hasNewAnswer {
                    toastMessage = "有人来一句了。"
                    showsToast = true
                    try? await Task.sleep(for: .milliseconds(1_400))
                    showsToast = false
                }
            }
        }
    }

    private func acceptAnswer() {
        Task { @MainActor in
            await session.acceptCurrentHelpAnswer()
            onHome()
        }
    }
}

struct AnswerScreen: View {
    let session: AppSession
    var showsTopBar: Bool = true

    @State private var draft = ""
    @State private var isLoading = true
    @State private var isSending = false
    @State private var showsToast = false
    @State private var toastMessage = "收到了，+10 等她采纳。"
    @State private var toastTask: Task<Void, Never>?

    var body: some View {
        AppChrome(showsBack: true, backAction: nil, showsTopBar: showsTopBar) {
            ZStack {
                VStack(spacing: 0) {
                    VStack(alignment: .leading, spacing: 5) {
                        Text("来一句")
                            .font(.system(size: 24, weight: .semibold))
                            .foregroundStyle(AppTheme.text)

                        Text("帮 TA 少纠结一次。")
                            .font(.system(size: 14))
                            .foregroundStyle(AppTheme.textSecondary)
                    }
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .padding(.horizontal, 8)
                    .padding(.top, 8)
                    .padding(.bottom, 14)

                    HelpDeckStack(
                        current: session.answerRequest,
                        next: session.nextAnswerRequest,
                        isLoading: isLoading,
                        onAdvance: {
                            session.advanceAnswerRequest()
                        }
                    )

                    Spacer(minLength: 18)
                }
                .padding(.horizontal, 14)
                .padding(.bottom, 14)

                ToastView(message: toastMessage, isVisible: showsToast)
            }
        } footer: {
            BottomComposer(
                text: $draft,
                placeholder: answerPlaceholder,
                isSending: isSending || session.answerRequest == nil
            ) {
                sendAnswer()
            }
        }
        .task {
            isLoading = true
            await session.loadAnswerQueue()
            isLoading = false
        }
        .onDisappear {
            toastTask?.cancel()
        }
    }

    private func sendAnswer() {
        let answer = draft.trimmingCharacters(in: .whitespacesAndNewlines)
        guard answer.count >= 2, let request = session.answerRequest else {
            toastMessage = "至少写两个字。"
            flashToast()
            return
        }
        draft = ""
        toastTask?.cancel()
        isSending = true
        toastMessage = "收到了，\(request.rewardLabel) 等她采纳。"
        toastTask = Task { @MainActor in
            await session.addAnswer(answer)
            isSending = false
            showsToast = true
            try? await Task.sleep(for: .milliseconds(1_600))
            guard !Task.isCancelled else { return }
            showsToast = false
        }
    }

    private func flashToast() {
        toastTask?.cancel()
        showsToast = true
        toastTask = Task { @MainActor in
            try? await Task.sleep(for: .milliseconds(1_200))
            guard !Task.isCancelled else { return }
            showsToast = false
        }
    }

    private var answerPlaceholder: String {
        guard let request = session.answerRequest else {
            return "等下一张求一个"
        }
        let title = request.title.trimmingCharacters(in: .whitespacesAndNewlines)
        if title.contains("明洞") || title.contains("韩国") || title.contains("小众") {
            return "别去明洞当背景板，去圣水。"
        }
        if title.contains("海底捞") || title.contains("不辣") {
            return "番茄锅更稳，别上红油。"
        }
        return "来一句，帮 TA 少纠结"
    }
}

struct HelpDeckStack: View {
    let current: HelpRequest?
    let next: HelpRequest?
    let isLoading: Bool
    let onAdvance: () -> Void

    @State private var dragOffset: CGFloat = 0
    @State private var committedSwipeCount = 0

    var body: some View {
        GeometryReader { proxy in
            let cardWidth = min(proxy.size.width - 30, 390)
            let cardHeight = min(max(proxy.size.height * 0.78, 420), 560)
            let dragProgress = min(abs(dragOffset) / max(cardWidth * 0.42, 1), 1)

            ZStack {
                if isLoading {
                    HelpDeckLoadingCard()
                        .frame(width: cardWidth, height: cardHeight)
                } else if let current {
                    if let next {
                        HelpDeckCard(request: next)
                            .frame(width: cardWidth, height: cardHeight)
                            .scaleEffect(0.95 + 0.03 * dragProgress)
                            .offset(x: dragOffset >= 0 ? -28 + 10 * dragProgress : 24 - 10 * dragProgress)
                            .opacity(0.52 + 0.18 * dragProgress)
                            .allowsHitTesting(false)
                    }

                    HelpDeckCard(request: current)
                        .frame(width: cardWidth, height: cardHeight)
                        .offset(x: dragOffset)
                        .scaleEffect(1 - 0.035 * dragProgress)
                        .rotationEffect(.degrees(Double(dragOffset / 36)))
                        .gesture(
                            DragGesture()
                                .onChanged { value in
                                    dragOffset = value.translation.width
                                }
                                .onEnded { value in
                                    if abs(value.translation.width) > 90 {
                                        withAnimation(.spring(response: 0.28, dampingFraction: 0.82)) {
                                            dragOffset = value.translation.width > 0 ? cardWidth : -cardWidth
                                        }
                                        committedSwipeCount += 1
                                        DispatchQueue.main.asyncAfter(deadline: .now() + 0.16) {
                                            onAdvance()
                                            withAnimation(.spring(response: 0.24, dampingFraction: 0.88)) {
                                                dragOffset = 0
                                            }
                                        }
                                    } else {
                                        withAnimation(.spring(response: 0.32, dampingFraction: 0.84)) {
                                            dragOffset = 0
                                        }
                                    }
                                }
                        )
                } else {
                    EmptyAnswerQueueCard()
                        .frame(width: cardWidth)
                }
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity)
            .sensoryFeedback(.selection, trigger: committedSwipeCount)
        }
    }
}

struct HelpDeckCard: View {
    let request: HelpRequest

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            HStack(alignment: .center) {
                Text("求一个")
                    .font(.system(size: 13, weight: .semibold))
                    .tracking(1.2)
                    .foregroundStyle(AppTheme.textMuted)

                Spacer()

                Text(request.rewardLabel)
                    .font(.system(size: 18, weight: .semibold))
                    .foregroundStyle(AppTheme.green)
            }

            Spacer(minLength: 24)

            Text(request.title)
                .font(.system(size: 32, weight: .semibold))
                .lineSpacing(4)
                .foregroundStyle(AppTheme.text)
                .lineLimit(3)
                .minimumScaleFactor(0.78)
                .frame(maxWidth: .infinity, alignment: .leading)
                .multilineTextAlignment(.leading)

            Text(request.context)
                .font(.system(size: 17))
                .lineSpacing(6)
                .foregroundStyle(AppTheme.textSecondary)
                .lineLimit(3)
                .multilineTextAlignment(.leading)
                .frame(maxWidth: .infinity, alignment: .leading)
                .padding(.top, 18)

            Spacer(minLength: 26)

            HStack(spacing: 8) {
                Text(request.answerCount > 0 ? "\(request.answerCount) 人已答" : "看懂了，就来一句。")
                    .font(.system(size: 14, weight: .medium))
                    .foregroundStyle(AppTheme.textSecondary)

                Spacer()
            }
        }
        .padding(24)
        .background(AppTheme.card)
        .clipShape(RoundedRectangle(cornerRadius: 28, style: .continuous))
        .overlay(
            RoundedRectangle(cornerRadius: 28, style: .continuous)
                .stroke(AppTheme.border, lineWidth: 1)
        )
        .shadow(color: .black.opacity(0.055), radius: 22, x: 0, y: 12)
        .accessibilityElement(children: .combine)
        .accessibilityLabel("求一个, \(request.title), \(request.rewardLabel)")
    }
}

struct HelpDeckLoadingCard: View {
    var body: some View {
        VStack(spacing: 14) {
            ProgressView()
                .tint(AppTheme.green)

            Text("正在取求一个")
                .font(.system(size: 15, weight: .medium))
                .foregroundStyle(AppTheme.textSecondary)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .background(AppTheme.card)
        .clipShape(RoundedRectangle(cornerRadius: 28, style: .continuous))
        .overlay(
            RoundedRectangle(cornerRadius: 28, style: .continuous)
                .stroke(AppTheme.border, lineWidth: 1)
        )
    }
}

struct ServiceNoticePill: View {
    let notice: ServiceNotice

    var body: some View {
        HStack(alignment: .top, spacing: 8) {
            Image(systemName: notice.title == "皮皮" ? "quote.bubble" : "exclamationmark.triangle")
                .font(.system(size: 12, weight: .semibold))
                .foregroundStyle(notice.title == "皮皮" ? AppTheme.textSecondary : AppTheme.orangeText)
                .padding(.top, 1)

            VStack(alignment: .leading, spacing: 2) {
                Text(notice.title)
                    .font(.system(size: 12, weight: .semibold))
                    .foregroundStyle(notice.title == "皮皮" ? AppTheme.text : AppTheme.orangeText)

                Text(notice.detail)
                    .font(.system(size: 12))
                    .lineSpacing(2)
                    .foregroundStyle(AppTheme.textSecondary)
                    .fixedSize(horizontal: false, vertical: true)
            }
        }
        .padding(.horizontal, 12)
        .padding(.vertical, 9)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(notice.title == "皮皮" ? AppTheme.card : AppTheme.orangeBackground)
        .clipShape(RoundedRectangle(cornerRadius: 12, style: .continuous))
        .accessibilityElement(children: .combine)
        .accessibilityLabel("\(notice.title), \(notice.detail)")
    }
}

struct EmptyAnswerQueueCard: View {
    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            Text("暂时没有求一个")
                .font(.system(size: 18, weight: .semibold))
                .foregroundStyle(AppTheme.text)

            Text("晚点再来，或者自己发一个。")
                .font(.system(size: 14))
                .lineSpacing(4)
                .foregroundStyle(AppTheme.textSecondary)
        }
        .padding(22)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(AppTheme.card)
        .clipShape(RoundedRectangle(cornerRadius: 24, style: .continuous))
        .overlay(
            RoundedRectangle(cornerRadius: 24, style: .continuous)
                .stroke(AppTheme.border, lineWidth: 1)
        )
        .shadow(color: .black.opacity(0.06), radius: 24, x: 0, y: 10)
    }
}


struct ProfileScreen: View {
    let session: AppSession
    let authRevision: Int
    let onManageAccount: () -> Void
    let onHistorySelect: (QuestionHistory) -> Void
    let onOpenAnswerDeck: () -> Void

    @State private var snapshot = UserDashboardSnapshot.empty
    @State private var isLoading = false

    private var signedIn: Bool {
        AuthTokenStore.email != nil
    }

    private var displayName: String {
        if let name = AuthTokenStore.displayName?.trimmingCharacters(in: .whitespacesAndNewlines), !name.isEmpty {
            return name
        }
        return signedIn ? "已登录" : "登录后同步记录"
    }

    private var accountSubtitle: String {
        AuthTokenStore.email ?? "邮箱验证码登录"
    }

    private var myHelpHistory: [QuestionHistory] {
        session.history.filter { item in
            item.helpRequestId != nil || item.status == "waiting_for_human" || item.status == "answer_received"
        }
    }

    private var recentChoices: [QuestionHistory] {
        session.history.filter { item in
            item.status == "top1" || item.status == "completed"
        }
    }

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 22) {
                accountCard
                metricGrid
                answerCallout

                profileHistorySection(
                    title: "我的求一个",
                    items: Array(myHelpHistory.prefix(3)),
                    emptyText: "还没有发过求一个"
                )

                profileHistorySection(
                    title: "最近选择",
                    items: Array(recentChoices.prefix(4)),
                    emptyText: "你的选择会出现在这里"
                )

                messageSection
                appInfoSection
            }
            .padding(.horizontal, 18)
            .padding(.top, 12)
            .padding(.bottom, 32)
        }
        .background(AppTheme.background.ignoresSafeArea())
        .navigationTitle("我的")
        .navigationBarTitleDisplayMode(.large)
        .toolbar {
            ToolbarItem(placement: .topBarTrailing) {
                Button {
                    Task { await loadSnapshot() }
                } label: {
                    if isLoading {
                        ProgressView()
                            .tint(AppTheme.text)
                    } else {
                        Image(systemName: "arrow.clockwise")
                            .font(.system(size: 16, weight: .semibold))
                    }
                }
                .disabled(isLoading)
                .accessibilityLabel("刷新")
            }
        }
        .refreshable {
            await loadSnapshot()
        }
        .task(id: authRevision) {
            await loadSnapshot()
        }
    }

    private var accountCard: some View {
        Button(action: onManageAccount) {
            HStack(spacing: 15) {
                ZStack {
                    Circle()
                        .fill(AppTheme.bubble)
                        .frame(width: 54, height: 54)

                    Image(systemName: signedIn ? "person.crop.circle.fill" : "person.crop.circle")
                        .font(.system(size: 28, weight: .medium))
                        .foregroundStyle(AppTheme.text)
                }

                VStack(alignment: .leading, spacing: 5) {
                    Text(displayName)
                        .font(.system(size: 19, weight: .semibold))
                        .foregroundStyle(AppTheme.text)

                    Text(accountSubtitle)
                        .font(.system(size: 14))
                        .foregroundStyle(AppTheme.textSecondary)
                        .lineLimit(1)
                }

                Spacer()

                Image(systemName: "chevron.right")
                    .font(.system(size: 13, weight: .semibold))
                    .foregroundStyle(AppTheme.textMuted)
            }
            .padding(18)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(AppTheme.card)
            .clipShape(RoundedRectangle(cornerRadius: 22, style: .continuous))
            .overlay(
                RoundedRectangle(cornerRadius: 22, style: .continuous)
                    .stroke(AppTheme.border, lineWidth: 1)
            )
        }
        .buttonStyle(.plain)
        .accessibilityLabel(signedIn ? "管理账号" : "邮箱登录")
    }

    private var metricGrid: some View {
        HStack(spacing: 10) {
            ProfileMetricTile(
                value: "\(snapshot.grantedReward)",
                label: "已得积分",
                secondary: snapshot.pendingReward > 0 ? "+\(snapshot.pendingReward) 待确认" : nil
            )
            ProfileMetricTile(
                value: "\(snapshot.answeredCount)",
                label: "来过一句",
                secondary: qualityTierLabel
            )
            ProfileMetricTile(
                value: "\(session.history.count)",
                label: "历史选择",
                secondary: nil
            )
        }
    }

    private var answerCallout: some View {
        Button(action: onOpenAnswerDeck) {
            HStack(spacing: 14) {
                Image(systemName: "bubble.left.and.bubble.right.fill")
                    .font(.system(size: 20, weight: .semibold))
                    .foregroundStyle(.white)
                    .frame(width: 44, height: 44)
                    .background(AppTheme.text)
                    .clipShape(Circle())

                VStack(alignment: .leading, spacing: 4) {
                    Text("来一句")
                        .font(.system(size: 17, weight: .semibold))
                        .foregroundStyle(AppTheme.text)
                    Text("刷一张求一个，顺手帮 TA 少纠结一次。")
                        .font(.system(size: 13))
                        .foregroundStyle(AppTheme.textSecondary)
                }

                Spacer()

                Image(systemName: "chevron.right")
                    .font(.system(size: 13, weight: .semibold))
                    .foregroundStyle(AppTheme.textMuted)
            }
            .padding(16)
            .background(AppTheme.card)
            .clipShape(RoundedRectangle(cornerRadius: 20, style: .continuous))
            .overlay(
                RoundedRectangle(cornerRadius: 20, style: .continuous)
                    .stroke(AppTheme.border, lineWidth: 1)
            )
        }
        .buttonStyle(.plain)
    }

    @ViewBuilder
    private func profileHistorySection(title: String, items: [QuestionHistory], emptyText: String) -> some View {
        VStack(alignment: .leading, spacing: 10) {
            ProfileSectionHeader(title: title)

            VStack(spacing: 0) {
                if items.isEmpty {
                    Text(emptyText)
                        .font(.system(size: 14))
                        .foregroundStyle(AppTheme.textMuted)
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .padding(16)
                } else {
                    ForEach(Array(items.enumerated()), id: \.element.id) { index, item in
                        Button {
                            onHistorySelect(item)
                        } label: {
                            ProfileHistoryRow(item: item)
                        }
                        .buttonStyle(.plain)

                        if index < items.count - 1 {
                            Divider()
                                .padding(.leading, 16)
                        }
                    }
                }
            }
            .background(AppTheme.card)
            .clipShape(RoundedRectangle(cornerRadius: 20, style: .continuous))
            .overlay(
                RoundedRectangle(cornerRadius: 20, style: .continuous)
                    .stroke(AppTheme.border, lineWidth: 1)
            )
        }
    }

    private var messageSection: some View {
        VStack(alignment: .leading, spacing: 10) {
            ProfileSectionHeader(title: "消息")

            VStack(spacing: 0) {
                if snapshot.lightEvents.isEmpty {
                    Text("暂时没有新消息")
                        .font(.system(size: 14))
                        .foregroundStyle(AppTheme.textMuted)
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .padding(16)
                } else {
                    ForEach(Array(snapshot.lightEvents.prefix(3).enumerated()), id: \.element.id) { index, event in
                        ProfileMessageRow(event: event)
                        if index < min(snapshot.lightEvents.count, 3) - 1 {
                            Divider()
                                .padding(.leading, 52)
                        }
                    }
                }
            }
            .background(AppTheme.card)
            .clipShape(RoundedRectangle(cornerRadius: 20, style: .continuous))
            .overlay(
                RoundedRectangle(cornerRadius: 20, style: .continuous)
                    .stroke(AppTheme.border, lineWidth: 1)
            )
        }
    }

    private var appInfoSection: some View {
        VStack(alignment: .leading, spacing: 10) {
            ProfileSectionHeader(title: "关于")

            VStack(spacing: 0) {
                Button(action: onManageAccount) {
                    HStack {
                        Label(signedIn ? "账号与登录" : "登录并同步", systemImage: "person.crop.circle")
                            .font(.system(size: 15, weight: .medium))
                            .foregroundStyle(AppTheme.text)
                        Spacer()
                        Image(systemName: "chevron.right")
                            .font(.system(size: 12, weight: .semibold))
                            .foregroundStyle(AppTheme.textMuted)
                    }
                    .padding(16)
                }
                .buttonStyle(.plain)

                Divider()
                    .padding(.leading, 16)

                HStack {
                    Label("版本", systemImage: "info.circle")
                        .font(.system(size: 15, weight: .medium))
                        .foregroundStyle(AppTheme.text)
                    Spacer()
                    Text(appVersion)
                        .font(.system(size: 14))
                        .foregroundStyle(AppTheme.textSecondary)
                }
                .padding(16)
            }
            .background(AppTheme.card)
            .clipShape(RoundedRectangle(cornerRadius: 20, style: .continuous))
            .overlay(
                RoundedRectangle(cornerRadius: 20, style: .continuous)
                    .stroke(AppTheme.border, lineWidth: 1)
            )
        }
    }

    private var qualityTierLabel: String? {
        switch snapshot.qualityTier {
        case "reliable": "靠谱答主"
        case "promising": "正在变靠谱"
        case "at_risk": "需要更认真"
        default: nil
        }
    }

    private var appVersion: String {
        let version = Bundle.main.object(forInfoDictionaryKey: "CFBundleShortVersionString") as? String ?? "0.1.0"
        let build = Bundle.main.object(forInfoDictionaryKey: "CFBundleVersion") as? String ?? "1"
        return "\(version) (\(build))"
    }

    @MainActor
    private func loadSnapshot() async {
        guard !isLoading else { return }
        isLoading = true
        snapshot = await ProfileAPIService().fetchSnapshot()
        isLoading = false
    }
}

private struct ProfileSectionHeader: View {
    let title: String

    var body: some View {
        Text(title)
            .font(.system(size: 13, weight: .semibold))
            .foregroundStyle(AppTheme.textSecondary)
            .padding(.horizontal, 2)
    }
}

private struct ProfileMetricTile: View {
    let value: String
    let label: String
    let secondary: String?

    var body: some View {
        VStack(alignment: .leading, spacing: 5) {
            Text(value)
                .font(.system(size: 23, weight: .semibold))
                .foregroundStyle(AppTheme.text)
                .lineLimit(1)
                .minimumScaleFactor(0.75)

            Text(label)
                .font(.system(size: 12, weight: .medium))
                .foregroundStyle(AppTheme.textSecondary)

            if let secondary {
                Text(secondary)
                    .font(.system(size: 10, weight: .medium))
                    .foregroundStyle(AppTheme.green)
                    .lineLimit(1)
            }
        }
        .padding(14)
        .frame(maxWidth: .infinity, minHeight: 98, alignment: .topLeading)
        .background(AppTheme.card)
        .clipShape(RoundedRectangle(cornerRadius: 18, style: .continuous))
        .overlay(
            RoundedRectangle(cornerRadius: 18, style: .continuous)
                .stroke(AppTheme.border, lineWidth: 1)
        )
    }
}

private struct ProfileHistoryRow: View {
    let item: QuestionHistory

    var body: some View {
        HStack(spacing: 12) {
            VStack(alignment: .leading, spacing: 5) {
                Text(item.query)
                    .font(.system(size: 15, weight: .medium))
                    .foregroundStyle(AppTheme.text)
                    .lineLimit(1)

                Text(item.statusLabel)
                    .font(.system(size: 12))
                    .foregroundStyle(AppTheme.textSecondary)
            }

            Spacer()

            Image(systemName: "chevron.right")
                .font(.system(size: 12, weight: .semibold))
                .foregroundStyle(AppTheme.textMuted)
        }
        .padding(16)
        .contentShape(Rectangle())
    }
}

private struct ProfileMessageRow: View {
    let event: UserLightEvent

    var body: some View {
        HStack(alignment: .top, spacing: 12) {
            Image(systemName: "lightbulb.fill")
                .font(.system(size: 15, weight: .semibold))
                .foregroundStyle(AppTheme.green)
                .frame(width: 34, height: 34)
                .background(AppTheme.bubble)
                .clipShape(Circle())

            VStack(alignment: .leading, spacing: 4) {
                Text(event.title)
                    .font(.system(size: 14, weight: .semibold))
                    .foregroundStyle(AppTheme.text)
                Text(event.body)
                    .font(.system(size: 13))
                    .lineSpacing(3)
                    .foregroundStyle(AppTheme.textSecondary)
                    .lineLimit(3)
            }

            Spacer(minLength: 0)
        }
        .padding(16)
    }
}

private enum UIPolishPreviewFixtures {
    static let pickWithImage = TopPick(
        cardId: UUID(),
        query: "我在三里屯，想吃川菜",
        preface: "别查了，就这个。",
        title: "三里屯川菜，就选这家",
        subtitle: "三里屯 · 川菜",
        reason: "离你近，口味稳，适合现在直接做决定。",
        bullets: ["不应该显示"],
        warning: "不应该显示",
        followups: ["不应该显示"],
        referenceImage: ReferenceImage(
            url: "https://images.unsplash.com/photo-1555396273-367ea4eb4db5",
            sourceURL: "https://unsplash.com",
            sourceDomain: "unsplash.com",
            caption: "餐厅",
            isAiGenerated: false
        )
    )

    static let pickWithoutImage = TopPick(
        cardId: UUID(),
        query: "帮我找一下朝阳区热干面",
        preface: "别查了，就这个。",
        title: "朝阳区热干面，就选这家",
        subtitle: "朝阳区 · 热干面",
        reason: "你要的是热干面，先选距离和口味容错率都稳的一家。",
        bullets: ["不应该显示"],
        warning: "不应该显示",
        followups: ["不应该显示"],
        referenceImage: nil
    )

    static let helpDraft = HelpRequest(
        title: "韩国逛街不去明洞，求一个小众路线",
        context: "想逛街，避开游客区，最好顺路能买点小东西。",
        rewardLabel: "+10",
        answerCount: 0,
        status: .draft
    )

    static let helpAnswered = HelpRequest(
        title: "三里屯海底捞，两个人不太能吃辣怎么点",
        context: "人在店里，两个人，想稳一点，不要太辣也别浪费。",
        rewardLabel: "+8",
        answerCount: 2,
        status: .published
    )
}

private struct BottomComposerPreviewHost: View {
    @State private var text = ""

    var body: some View {
        VStack {
            Spacer()
            BottomComposer(text: $text, placeholder: "来一句，帮 TA 少纠结") {}
        }
        .appScreenBackground()
    }
}

#Preview("Input") {
    InputScreen(
        session: AppSession(service: MockCloudRecommendationService()),
        onDecision: { _ in },
        onMenu: {},
        onHistorySelect: { _ in }
    )
}

#Preview("Result") {
    ResultScreen(session: AppSession(service: MockCloudRecommendationService()), onAskHuman: {}, onDecision: { _ in }, onAccepted: {}, onBackHome: {})
}

#Preview("Ask") {
    AskScreen(session: AppSession(service: MockCloudRecommendationService()), onHome: {})
}

#Preview("Answer") {
    AnswerScreen(session: AppSession(service: MockCloudRecommendationService()))
}

#Preview("Recommendation Card · Image") {
    ChatRecommendationCard(
        pick: UIPolishPreviewFixtures.pickWithImage,
        isAccepting: false,
        onAskHuman: {},
        onAccept: {}
    )
    .padding()
    .appScreenBackground()
}

#Preview("Recommendation Card · No Image") {
    ChatRecommendationCard(
        pick: UIPolishPreviewFixtures.pickWithoutImage,
        isAccepting: false,
        onAskHuman: {},
        onAccept: {}
    )
    .padding()
    .appScreenBackground()
}

#Preview("Help Card · Draft") {
    ChatHelpCard(
        request: UIPolishPreviewFixtures.helpDraft,
        isPublishing: false,
        onPublish: {}
    )
    .padding()
    .appScreenBackground()
}

#Preview("Help Deck Card") {
    HelpDeckCard(request: UIPolishPreviewFixtures.helpAnswered)
        .frame(width: 370, height: 520)
        .padding()
        .appScreenBackground()
}

#Preview("Bottom Composer") {
    BottomComposerPreviewHost()
}
