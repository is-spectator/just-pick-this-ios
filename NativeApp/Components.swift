import SwiftUI

struct AppChrome<Content: View, Footer: View>: View {
    let showsBack: Bool
    let backAction: (() -> Void)?
    let onHistory: (() -> Void)?
    let onNewConversation: (() -> Void)?
    let showsHistoryBadge: Bool
    let showsTopBar: Bool
    @ViewBuilder let content: Content
    @ViewBuilder let footer: Footer

    @Environment(\.dismiss) private var dismiss

    init(
        showsBack: Bool,
        backAction: (() -> Void)?,
        onHistory: (() -> Void)? = nil,
        onNewConversation: (() -> Void)? = nil,
        showsHistoryBadge: Bool = false,
        showsTopBar: Bool = true,
        @ViewBuilder content: () -> Content,
        @ViewBuilder footer: () -> Footer
    ) {
        self.showsBack = showsBack
        self.backAction = backAction
        self.onHistory = onHistory
        self.onNewConversation = onNewConversation
        self.showsHistoryBadge = showsHistoryBadge
        self.showsTopBar = showsTopBar
        self.content = content()
        self.footer = footer()
    }

    var body: some View {
        VStack(spacing: 0) {
            if showsTopBar {
                TopBar(
                    showsBack: showsBack,
                    onHistory: onHistory,
                    onNewConversation: onNewConversation,
                    showsHistoryBadge: showsHistoryBadge
                ) {
                    if let backAction {
                        backAction()
                    } else {
                        dismiss()
                    }
                }
            }

            content
                .frame(maxWidth: .infinity, maxHeight: .infinity)

            footer
        }
        .appScreenBackground()
        .navigationBarBackButtonHidden(true)
    }
}

struct TopBar: View {
    let showsBack: Bool
    let onHistory: (() -> Void)?
    let onNewConversation: (() -> Void)?
    let showsHistoryBadge: Bool
    let onBack: () -> Void

    init(
        showsBack: Bool,
        onHistory: (() -> Void)?,
        onNewConversation: (() -> Void)?,
        showsHistoryBadge: Bool = false,
        onBack: @escaping () -> Void
    ) {
        self.showsBack = showsBack
        self.onHistory = onHistory
        self.onNewConversation = onNewConversation
        self.showsHistoryBadge = showsHistoryBadge
        self.onBack = onBack
    }

    var body: some View {
        if showsBack {
            HStack {
                Button(action: onBack) {
                    Image(systemName: "chevron.left")
                        .font(.system(size: 22, weight: .medium))
                        .foregroundStyle(AppTheme.text)
                        .frame(width: 44, height: 44, alignment: .leading)
                        .contentShape(Rectangle())
                }
                .buttonStyle(.plain)
                .accessibilityLabel("返回")

                Spacer()

                Text("就选这个")
                    .font(.system(size: 15, weight: .semibold))
                    .foregroundStyle(AppTheme.text)

                Spacer()

                Color.clear
                    .frame(width: 44, height: 44)
            }
            .padding(.horizontal, 16)
            .frame(height: 50)
        } else {
            ZStack {
                HStack(spacing: 0) {
                    if let onHistory {
                        Button(action: onHistory) {
                            ZStack(alignment: .topTrailing) {
                                Image(systemName: "line.3.horizontal")
                                    .font(AppTheme.Icon.toolbar)
                                    .foregroundStyle(AppTheme.text)
                                    .frame(width: 44, height: 44)

                                if showsHistoryBadge {
                                    Circle()
                                        .fill(AppTheme.red)
                                        .frame(width: 8, height: 8)
                                        .offset(x: -7, y: 9)
                                }
                            }
                        }
                        .buttonStyle(.plain)
                        .accessibilityLabel(showsHistoryBadge ? "打开菜单，有新消息" : "打开菜单")
                        .accessibilityHint(showsHistoryBadge ? "打开历史、来一句、收藏、消息中心和账号入口" : "打开历史、来一句、收藏和账号入口")
                    } else {
                        Color.clear
                            .frame(width: 44, height: 44)
                    }

                    Spacer()

                    if let onNewConversation {
                        Button(action: onNewConversation) {
                            HStack(spacing: 6) {
                                Image(systemName: "plus.message")
                                    .font(.system(size: 15, weight: .semibold))
                                Text("新对话")
                                    .font(.system(size: 15, weight: .semibold))
                            }
                            .foregroundStyle(AppTheme.text)
                            .padding(.horizontal, 13)
                            .frame(height: 40)
                            .background(AppTheme.bubble)
                            .clipShape(Capsule())
                            .contentShape(Capsule())
                            .appMinimumTouchTarget()
                        }
                        .buttonStyle(.plain)
                        .accessibilityLabel("新对话")
                        .accessibilityHint("清空当前聊天并开始新的选择")
                    } else {
                        Color.clear
                            .frame(width: 86, height: 40)
                    }
                }

                Text("皮皮")
                    .font(AppTheme.Typography.nav)
                    .foregroundStyle(AppTheme.text)
                    .accessibilityAddTraits(.isHeader)
            }
            .padding(.horizontal, AppTheme.Spacing.lg)
            .frame(height: 58)
        }
    }
}

struct BottomComposer: View {
    @Binding var text: String
    @Binding private var externalFocus: Bool
    let placeholder: String
    let isSending: Bool
    let onSend: () -> Void

    @FocusState private var isFocused: Bool
    @State private var sendFeedbackCount = 0

    private var canSend: Bool {
        !isSending && !text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
    }

    private func send() {
        guard canSend else { return }
        sendFeedbackCount += 1
        isFocused = false
        externalFocus = false
        onSend()
    }

    init(
        text: Binding<String>,
        placeholder: String,
        focused: Binding<Bool> = .constant(false),
        isSending: Bool = false,
        onSend: @escaping () -> Void
    ) {
        self._text = text
        self._externalFocus = focused
        self.placeholder = placeholder
        self.isSending = isSending
        self.onSend = onSend
    }

    var body: some View {
        HStack(spacing: 8) {
            TextField(placeholder, text: $text, axis: .vertical)
                .focused($isFocused)
                .font(.system(size: 15))
                .foregroundStyle(AppTheme.text)
                .lineLimit(1...3)
                .textInputAutocapitalization(.never)
                .submitLabel(.send)
                .disabled(isSending)
                .onSubmit {
                    send()
                }

            Button(action: send) {
                ZStack {
                    if isSending {
                        ProgressView()
                            .tint(AppTheme.onPrimaryAction)
                            .scaleEffect(0.74)
                    } else {
                        Image(systemName: "arrow.up")
                            .font(.system(size: 17, weight: .semibold))
                            .foregroundStyle(canSend ? AppTheme.onPrimaryAction : AppTheme.textMuted)
                    }
                }
                .frame(width: 32, height: 32)
                .background(canSend || isSending ? AppTheme.primaryAction : AppTheme.disabled)
                .clipShape(Circle())
                .frame(width: 44, height: 44)
                .contentShape(Circle())
            }
            .disabled(!canSend)
            .accessibilityLabel("发送")
        }
        .padding(.leading, 18)
        .padding(.trailing, 6)
        .padding(.vertical, 7)
        .frame(minHeight: 56, maxHeight: 120)
        .background(AppTheme.card)
        .clipShape(Capsule())
        .overlay(
            Capsule()
                .stroke(isFocused ? AppTheme.primaryAction.opacity(0.9) : AppTheme.border, lineWidth: 1)
        )
        .shadow(color: .black.opacity(0.04), radius: 2, x: 0, y: 1)
        .padding(.horizontal, 16)
        .padding(.top, 10)
        .padding(.bottom, 8)
        .background(AppTheme.background)
        .toolbar {
            ToolbarItemGroup(placement: .keyboard) {
                Spacer()
                Button("收起") {
                    isFocused = false
                    externalFocus = false
                }
                .font(.system(size: 15, weight: .semibold))
                .accessibilityLabel("收起键盘")
            }
        }
        .onChange(of: externalFocus) { _, focused in
            guard focused != isFocused else { return }
            isFocused = focused
        }
        .onChange(of: isFocused) { _, focused in
            guard focused != externalFocus else { return }
            externalFocus = focused
        }
        .onChange(of: isSending) { _, sending in
            if sending {
                isFocused = false
                externalFocus = false
            }
        }
        .sensoryFeedback(.selection, trigger: sendFeedbackCount)
    }
}

struct QueryBubble: View {
    let text: String

    var body: some View {
        HStack {
            Spacer()
            Text(text)
                .font(.system(size: 14))
                .lineSpacing(2)
                .foregroundStyle(AppTheme.text)
                .padding(.horizontal, 14)
                .padding(.vertical, 10)
                .background(AppTheme.bubble)
                .clipShape(RoundedRectangle(cornerRadius: 18, style: .continuous))
                .frame(maxWidth: 315, alignment: .trailing)
        }
        .padding(.top, 4)
        .padding(.bottom, 18)
    }
}

struct RecommendationImageSkeleton: View {
    @State private var isBreathing = false

    var body: some View {
        ZStack(alignment: .bottomLeading) {
            AppTheme.bubble
                .opacity(isBreathing ? 0.72 : 0.46)

            VStack(alignment: .leading, spacing: 8) {
                Capsule()
                    .fill(AppTheme.textMuted.opacity(0.16))
                    .frame(width: 96, height: 10)
                Capsule()
                    .fill(AppTheme.textMuted.opacity(0.12))
                    .frame(width: 148, height: 10)
            }
            .padding(18)
        }
        .onAppear {
            withAnimation(.easeInOut(duration: 0.95).repeatForever(autoreverses: true)) {
                isBreathing = true
            }
        }
        .accessibilityHidden(true)
    }
}

enum CardTextFitting {
    static func recommendationTitleSize(_ title: String, hasImage: Bool, compact: Bool = false) -> CGFloat {
        let count = title.count
        if compact {
            if count > 26 { return 24 }
            if count > 18 { return 26 }
            return hasImage ? 28 : 30
        }

        if count > 28 { return hasImage ? 24 : 26 }
        if count > 20 { return hasImage ? 27 : 29 }
        return hasImage ? 31 : 34
    }

    static func requestTitleSize(_ title: String, compact: Bool = false) -> CGFloat {
        let count = title.count
        if compact {
            if count > 28 { return 19 }
            if count > 18 { return 21 }
            return 23
        }

        if count > 30 { return 20 }
        if count > 20 { return 22 }
        return 24
    }
}

struct CollapsibleText: View {
    let text: String
    let font: Font
    let color: Color
    var collapsedLineLimit: Int = 3
    var lineSpacing: CGFloat = 4
    var expandThreshold: Int = 78

    @State private var isExpanded = false

    private var trimmedText: String {
        text.trimmingCharacters(in: .whitespacesAndNewlines)
    }

    private var shouldOfferExpansion: Bool {
        trimmedText.count > expandThreshold || trimmedText.contains("\n")
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            Text(trimmedText)
                .font(font)
                .lineSpacing(lineSpacing)
                .foregroundStyle(color)
                .lineLimit(isExpanded ? nil : collapsedLineLimit)
                .fixedSize(horizontal: false, vertical: true)

            if shouldOfferExpansion {
                Button {
                    withAnimation(.easeInOut(duration: 0.18)) {
                        isExpanded.toggle()
                    }
                } label: {
                    Text(isExpanded ? "收起" : "展开")
                        .font(.system(size: 13, weight: .semibold))
                        .foregroundStyle(AppTheme.text)
                }
                .buttonStyle(.plain)
                .accessibilityLabel(isExpanded ? "收起全文" : "展开全文")
            }
        }
    }
}

enum RecommendationFeedbackState: Equatable {
    case change
    case issue
}

struct DecisionCard: View {
    let pick: TopPick
    let isFollowingUp: Bool
    let isAccepting: Bool
    let onFollowup: (String) -> Void
    let onAskHuman: () -> Void
    let onReject: () -> Void
    let onFavorite: () -> Void
    let onReportIssue: () -> Void
    let onShare: () -> Void
    let onAccept: () -> Void

    @State private var imageLoadFailed = false
    @State private var hasAppeared = false
    @State private var acceptFeedbackCount = 0
    @State private var feedbackState: RecommendationFeedbackState?

    private var imageURL: URL? {
        guard !imageLoadFailed else { return nil }
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
                    .overlay(alignment: .topTrailing) {
                        RecommendationOverflowMenu(
                            feedbackState: feedbackState,
                            onFavorite: onFavorite,
                            onShare: onShare,
                            onChange: markChange,
                            onReportIssue: markIssue
                        )
                            .padding(12)
                    }
            } else {
                HStack {
                    Spacer()
                    RecommendationOverflowMenu(
                        feedbackState: feedbackState,
                        onFavorite: onFavorite,
                        onShare: onShare,
                        onChange: markChange,
                        onReportIssue: markIssue
                    )
                }
            }

            VStack(alignment: .leading, spacing: 12) {
                if let supportingSubtitle {
                    Text(supportingSubtitle)
                        .font(.system(size: 15, weight: .medium))
                        .foregroundStyle(AppTheme.textSecondary)
                        .lineLimit(2)
                }

                Text(pick.title)
                    .font(.system(size: CardTextFitting.recommendationTitleSize(pick.title, hasImage: imageURL != nil), weight: .bold))
                    .lineSpacing(3)
                    .foregroundStyle(AppTheme.text)
                    .lineLimit(3)
                    .minimumScaleFactor(0.74)

                Text(decisionReason)
                    .font(.system(size: 20, weight: .medium))
                    .lineSpacing(5)
                    .foregroundStyle(AppTheme.textSecondary)
                    .lineLimit(2)
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
                .accessibilityHint("把这个问题发给别人来一句")

                Button {
                    acceptFeedbackCount += 1
                    onAccept()
                } label: {
                    HStack(spacing: 8) {
                        if isAccepting {
                            ProgressView()
                                .tint(AppTheme.onPrimaryAction)
                                .scaleEffect(0.76)
                        }

                        Text(isAccepting ? "确认中" : "就这个")
                            .font(.system(size: 16, weight: .semibold))
                    }
                    .foregroundStyle(AppTheme.onPrimaryAction)
                    .frame(maxWidth: .infinity)
                    .frame(height: 52)
                    .background(AppTheme.primaryAction)
                    .clipShape(Capsule())
                }
                .buttonStyle(.plain)
                .disabled(isAccepting)
                .accessibilityLabel("就这个")
                .accessibilityHint("采纳皮皮给出的这个选择")
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

    private func markChange() {
        feedbackState = .change
        onReject()
    }

    private func markIssue() {
        feedbackState = .issue
        onReportIssue()
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
                        .task {
                            withAnimation(.easeInOut(duration: 0.18)) {
                                imageLoadFailed = true
                            }
                        }
                case .empty:
                    RecommendationImageSkeleton()
                @unknown default:
                    Color.clear
                        .task {
                            withAnimation(.easeInOut(duration: 0.18)) {
                                imageLoadFailed = true
                            }
                        }
                }
            }
            .frame(maxWidth: .infinity)
            .frame(height: 228)
            .clipShape(RoundedRectangle(cornerRadius: 22, style: .continuous))
            .clipped()
            .accessibilityHidden(true)
        }
    }
}

struct RecommendationOverflowMenu: View {
    var feedbackState: RecommendationFeedbackState?
    let onFavorite: () -> Void
    let onShare: () -> Void
    let onChange: () -> Void
    let onReportIssue: () -> Void

    init(
        feedbackState: RecommendationFeedbackState? = nil,
        onFavorite: @escaping () -> Void = {},
        onShare: @escaping () -> Void = {},
        onChange: @escaping () -> Void = {},
        onReportIssue: @escaping () -> Void = {}
    ) {
        self.feedbackState = feedbackState
        self.onFavorite = onFavorite
        self.onShare = onShare
        self.onChange = onChange
        self.onReportIssue = onReportIssue
    }

    var body: some View {
        Menu {
            Button(action: onFavorite) {
                Label("收藏", systemImage: "bookmark")
            }

            Button(action: onShare) {
                Label("分享", systemImage: "square.and.arrow.up")
            }

            Button(action: onChange) {
                Label(
                    feedbackState == .change ? "已标记不合适" : "不合适，换一个",
                    systemImage: feedbackState == .change ? "checkmark.circle" : "arrow.triangle.2.circlepath"
                )
            }
            .disabled(feedbackState == .change)

            Button(role: .destructive, action: onReportIssue) {
                Label(
                    feedbackState == .issue ? "已标记信息有误" : "信息有误",
                    systemImage: feedbackState == .issue ? "checkmark.circle" : "exclamationmark.bubble"
                )
            }
            .disabled(feedbackState == .issue)
        } label: {
            Image(systemName: "ellipsis")
                .font(.system(size: 17, weight: .semibold))
                .foregroundStyle(AppTheme.textSecondary)
                .frame(width: 44, height: 44)
                .background(.ultraThinMaterial)
                .clipShape(Circle())
        }
        .buttonStyle(.plain)
        .accessibilityLabel("更多推荐操作")
    }
}

struct ReferenceWebPreview: View {
    let image: ReferenceImage

    private var imageURL: URL? {
        URL(string: image.url)
    }

    private var sourceURL: URL? {
        guard let sourceURL = image.sourceURL else { return nil }
        return URL(string: sourceURL)
    }

    private var sourceLabel: String {
        if let caption = image.caption?.trimmingCharacters(in: .whitespacesAndNewlines),
           !caption.isEmpty,
           caption != "引用图",
           !caption.hasPrefix("引用网页") {
            return caption
        }
        return sourceURL == nil ? "参考图片" : "图片来源"
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 9) {
            AsyncImage(url: imageURL) { phase in
                switch phase {
                case .success(let loadedImage):
                    loadedImage
                        .resizable()
                        .scaledToFit()
                        .frame(maxWidth: .infinity, maxHeight: 160)
                        .padding(10)
                case .failure:
                    referencePlaceholder(title: "图片加载失败")
                case .empty:
                    ProgressView()
                        .tint(AppTheme.textMuted)
                        .frame(maxWidth: .infinity, minHeight: 150)
                @unknown default:
                    referencePlaceholder(title: "参考图片")
                }
            }
            .frame(maxWidth: .infinity, minHeight: 150)
            .background(AppTheme.bubble.opacity(0.7))
            .clipShape(RoundedRectangle(cornerRadius: 16, style: .continuous))

            if let sourceURL {
                Link(destination: sourceURL) {
                    sourceRow
                }
                .buttonStyle(.plain)
            } else {
                sourceRow
            }
        }
        .accessibilityElement(children: .combine)
        .accessibilityLabel(sourceLabel)
    }

    private var sourceRow: some View {
        HStack(spacing: 7) {
            Image(systemName: "safari")
                .font(.system(size: 12, weight: .medium))

            Text(sourceLabel)
                .font(.system(size: 12, weight: .medium))
                .lineLimit(1)

            Spacer(minLength: 6)

            if sourceURL != nil {
                Image(systemName: "arrow.up.right")
                    .font(.system(size: 10, weight: .bold))
            }
        }
        .foregroundStyle(AppTheme.textSecondary)
        .padding(.horizontal, 11)
        .padding(.vertical, 8)
        .background(AppTheme.bubble)
        .clipShape(Capsule())
        .appMinimumTouchTarget()
    }

    private func referencePlaceholder(title: String) -> some View {
        VStack(spacing: 8) {
            Image(systemName: "photo")
                .font(.system(size: 22, weight: .medium))
            Text(title)
                .font(.system(size: 12, weight: .medium))
        }
        .foregroundStyle(AppTheme.textMuted)
        .frame(maxWidth: .infinity, minHeight: 150)
    }
}

struct RejectIconButton: View {
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            ZStack {
                Circle()
                    .fill(AppTheme.red)
                    .frame(width: 38, height: 38)

                Image(systemName: "xmark")
                    .font(.system(size: 17, weight: .bold))
                    .foregroundStyle(Color.white)
            }
            .frame(width: 44, height: 44)
        }
        .buttonStyle(.plain)
        .accessibilityLabel("不采纳")
    }
}

struct AcceptIconButton: View {
    let isLoading: Bool
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            ZStack {
                Circle()
                    .fill(AppTheme.green)
                    .frame(width: 38, height: 38)

                if isLoading {
                    ProgressView()
                        .tint(Color.white)
                        .scaleEffect(0.72)
                } else {
                    Image(systemName: "checkmark")
                        .font(.system(size: 18, weight: .bold))
                        .foregroundStyle(Color.white)
                }
            }
            .frame(width: 44, height: 44)
        }
        .buttonStyle(.plain)
        .disabled(isLoading)
        .accessibilityLabel("采纳这个")
    }
}

struct FollowupSuggestions: View {
    let suggestions: [String]
    let isLoading: Bool
    let onFollowup: (String) -> Void
    let onAskHuman: () -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack(spacing: 8) {
                Text("继续问")
                    .font(.system(size: 12, weight: .medium))
                    .foregroundStyle(AppTheme.textMuted)

                if isLoading {
                    ProgressView()
                        .tint(AppTheme.textMuted)
                        .scaleEffect(0.72)
                }
            }

            FlowLayout(spacing: 8, rowSpacing: 8) {
                ForEach(suggestions, id: \.self) { suggestion in
                    FollowupChip(label: suggestion, isDisabled: isLoading) {
                        onFollowup(suggestion)
                    }
                }

                FollowupChip(label: "问真人", icon: "person.crop.circle.badge.questionmark", isDisabled: isLoading, action: onAskHuman)
            }
        }
    }
}

struct FollowupChip: View {
    let label: String
    let icon: String?
    let isDisabled: Bool
    let action: () -> Void

    init(label: String, icon: String? = nil, isDisabled: Bool, action: @escaping () -> Void) {
        self.label = label
        self.icon = icon
        self.isDisabled = isDisabled
        self.action = action
    }

    var body: some View {
        Button(action: action) {
            HStack(spacing: 6) {
                if let icon {
                    Image(systemName: icon)
                        .font(.system(size: 12, weight: .medium))
                }
                Text(label)
                    .font(.system(size: 13, weight: .medium))
                    .lineLimit(1)
            }
            .foregroundStyle(AppTheme.text)
            .padding(.horizontal, 12)
            .padding(.vertical, 9)
            .background(AppTheme.bubble)
            .clipShape(Capsule())
            .overlay(
                Capsule()
                    .stroke(AppTheme.borderSoft, lineWidth: 1)
            )
            .appMinimumTouchTarget()
            .opacity(isDisabled ? 0.52 : 1)
        }
        .disabled(isDisabled)
        .buttonStyle(.plain)
        .accessibilityLabel(label)
    }
}

struct FlowLayout: Layout {
    let spacing: CGFloat
    let rowSpacing: CGFloat

    func sizeThatFits(proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) -> CGSize {
        let maxWidth = proposal.width ?? 0
        let rows = rows(in: maxWidth, subviews: subviews)
        return CGSize(
            width: maxWidth,
            height: rows.last.map { $0.y + $0.height } ?? 0
        )
    }

    func placeSubviews(in bounds: CGRect, proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) {
        for row in rows(in: bounds.width, subviews: subviews) {
            for item in row.items {
                subviews[item.index].place(
                    at: CGPoint(x: bounds.minX + item.x, y: bounds.minY + row.y),
                    proposal: ProposedViewSize(item.size)
                )
            }
        }
    }

    private func rows(in maxWidth: CGFloat, subviews: Subviews) -> [FlowRow] {
        guard maxWidth > 0 else { return [] }

        var rows: [FlowRow] = []
        var currentItems: [FlowItem] = []
        var currentX: CGFloat = 0
        var currentHeight: CGFloat = 0
        var currentY: CGFloat = 0

        for index in subviews.indices {
            let size = subviews[index].sizeThatFits(.unspecified)
            let itemWidth = min(size.width, maxWidth)
            let shouldWrap = !currentItems.isEmpty && currentX + itemWidth > maxWidth

            if shouldWrap {
                rows.append(FlowRow(y: currentY, height: currentHeight, items: currentItems))
                currentY += currentHeight + rowSpacing
                currentItems = []
                currentX = 0
                currentHeight = 0
            }

            currentItems.append(
                FlowItem(index: index, x: currentX, size: CGSize(width: itemWidth, height: size.height))
            )
            currentX += itemWidth + spacing
            currentHeight = max(currentHeight, size.height)
        }

        if !currentItems.isEmpty {
            rows.append(FlowRow(y: currentY, height: currentHeight, items: currentItems))
        }

        return rows
    }
}

private struct FlowRow {
    let y: CGFloat
    let height: CGFloat
    let items: [FlowItem]
}

private struct FlowItem {
    let index: Int
    let x: CGFloat
    let size: CGSize
}

struct RequestCard: View {
    let request: HelpRequest
    let reward: String?

    init(request: HelpRequest, reward: String? = nil) {
        self.request = request
        self.reward = reward
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            HStack {
                Text("求一个")
                    .font(.system(size: 11, weight: .medium))
                    .tracking(1.6)
                    .foregroundStyle(AppTheme.textMuted)

                Spacer()

                if let reward {
                    Text(reward)
                        .font(.system(size: 12, weight: .semibold))
                        .foregroundStyle(AppTheme.green)
                } else {
                    Text(request.status.label)
                        .font(.system(size: 12, weight: .medium))
                        .foregroundStyle(AppTheme.textMuted)
                }
            }

            Text(request.title)
                .font(.system(size: CardTextFitting.requestTitleSize(request.title), weight: .semibold))
                .lineSpacing(2)
                .foregroundStyle(AppTheme.text)
                .lineLimit(3)
                .minimumScaleFactor(0.82)
                .padding(.top, 14)

            CollapsibleText(
                text: request.context,
                font: .system(size: 13),
                color: AppTheme.textSecondary,
                collapsedLineLimit: 3,
                lineSpacing: 4,
                expandThreshold: 88
            )
                .padding(.top, 12)

            HelpStructuredSummary(request: request)
                .padding(.top, 16)

            HelpRequestStatusSummary(request: request)
                .padding(.top, 14)

            if !request.answers.isEmpty {
                VStack(alignment: .leading, spacing: 12) {
                    Text("已收到一句")
                        .font(.system(size: 12, weight: .medium))
                        .foregroundStyle(AppTheme.textMuted)

                    ForEach(request.answers) { answer in
                        VStack(alignment: .leading, spacing: 8) {
                            Text(answer.text)
                                .font(.system(size: 15, weight: .medium))
                                .lineSpacing(4)
                                .foregroundStyle(AppTheme.text)

                            Text("\(answer.nickname) · \(answer.timeLabel)")
                                .font(.system(size: 12))
                                .foregroundStyle(AppTheme.textMuted)
                        }
                        .frame(maxWidth: .infinity, alignment: .leading)
                    }
                }
                .padding(.top, 18)
                .overlay(alignment: .top) {
                    Rectangle()
                        .fill(AppTheme.borderSoft)
                        .frame(height: 1)
                }
                .padding(.top, 18)
            }
        }
        .cardStyle()
    }
}

struct HelpRequestStatusSummary: View {
    let request: HelpRequest

    private var statusColor: Color {
        switch request.status {
        case .draft:
            AppTheme.textSecondary
        case .published:
            AppTheme.orangeText
        case .answered:
            AppTheme.green
        case .completed:
            AppTheme.green
        case .closed:
            AppTheme.textMuted
        }
    }

    private var statusIcon: String {
        switch request.status {
        case .draft:
            "square.and.pencil"
        case .published:
            "paperplane"
        case .answered:
            "quote.bubble"
        case .completed:
            "checkmark.seal"
        case .closed:
            "xmark.circle"
        }
    }

    private var detailText: String {
        let count = max(request.answerCount, request.answers.count)
        switch request.status {
        case .draft:
            return "还没发布，补完背景后可以发出去。"
        case .published:
            return count == 0 ? "正在等懂的人来一句。" : "已收到 \(count) 句，继续等更稳。"
        case .answered:
            return count == 0 ? "已有回答，可以去看详情。" : "已收到 \(count) 句，可以采纳或继续等。"
        case .completed:
            return "已经采纳，结果可回看。"
        case .closed:
            return "已关闭，不再继续收集来一句。"
        }
    }

    var body: some View {
        HStack(alignment: .top, spacing: 11) {
            Image(systemName: statusIcon)
                .font(.system(size: 13, weight: .semibold))
                .foregroundStyle(statusColor)
                .frame(width: 30, height: 30)
                .background(statusColor.opacity(0.12))
                .clipShape(Circle())

            VStack(alignment: .leading, spacing: 3) {
                HStack(spacing: 8) {
                    Text(request.status.label)
                        .font(.system(size: 12, weight: .semibold))
                        .foregroundStyle(statusColor)

                    Text(request.rewardLabel)
                        .font(.system(size: 12, weight: .semibold))
                        .foregroundStyle(AppTheme.green)
                }

                Text(detailText)
                    .font(AppTheme.Typography.caption)
                    .lineSpacing(3)
                    .foregroundStyle(AppTheme.textSecondary)
                    .fixedSize(horizontal: false, vertical: true)
            }

            Spacer(minLength: 0)
        }
        .padding(12)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(AppTheme.bubble.opacity(0.78))
        .clipShape(RoundedRectangle(cornerRadius: AppTheme.Radius.chip, style: .continuous))
        .accessibilityElement(children: .combine)
        .accessibilityLabel("\(request.status.label), \(detailText)")
    }
}

struct HelpStructuredSummary: View {
    let request: HelpRequest
    var compact: Bool = false

    private var rows: [(String, String)] {
        var result: [(String, String)] = []
        if let location {
            result.append(("地点/场景", location))
        }
        result.append(("想要", wantText))
        if let avoidText {
            result.append(("不要", avoidText))
        }
        if let constraintText {
            result.append(("限制", constraintText))
        }
        return result
    }

    var body: some View {
        VStack(alignment: .leading, spacing: compact ? 8 : 10) {
            ForEach(Array(rows.enumerated()), id: \.offset) { _, row in
                HStack(alignment: .top, spacing: 10) {
                    Text(row.0)
                        .font(.system(size: compact ? 11 : 12, weight: .medium))
                        .foregroundStyle(AppTheme.textMuted)
                        .frame(width: compact ? 58 : 70, alignment: .leading)

                    Text(row.1)
                        .font(.system(size: compact ? 13 : 14, weight: .medium))
                        .lineSpacing(3)
                        .foregroundStyle(AppTheme.textSecondary)
                        .fixedSize(horizontal: false, vertical: true)
                }
            }
        }
        .padding(compact ? 12 : 14)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(AppTheme.bubble.opacity(0.78))
        .clipShape(RoundedRectangle(cornerRadius: AppTheme.Radius.chip, style: .continuous))
    }

    private var searchableText: String {
        "\(request.title) \(request.context)"
    }

    private var location: String? {
        let candidates = ["韩国", "明洞", "圣水", "五道口", "海底捞", "三里屯", "朝阳", "望京", "北京", "上海", "互联宝地", "南锣鼓巷"]
        let matches = candidates.filter { searchableText.localizedCaseInsensitiveContains($0) }
        guard !matches.isEmpty else { return trimmedContextLine }
        return matches.prefix(3).joined(separator: " · ")
    }

    private var wantText: String {
        if searchableText.contains("点菜") || searchableText.contains("帮我点") || searchableText.contains("怎么点") {
            return "直接给一套点单"
        }
        if searchableText.contains("小众") {
            return "小众一点，别太游客"
        }
        if searchableText.contains("清淡") || searchableText.contains("清爽") || searchableText.contains("不辣") {
            return "清淡、稳妥、不折腾"
        }
        if searchableText.contains("韩餐") {
            return "韩餐里直接选一个"
        }
        return "让懂的人直接给一个选择"
    }

    private var avoidText: String? {
        if searchableText.contains("不去明洞") {
            return "不去明洞"
        }
        if searchableText.contains("不辣") || searchableText.contains("不能吃辣") || searchableText.contains("不太能吃辣") {
            return "重辣、红油锅"
        }
        if searchableText.contains("不要游客") || searchableText.contains("游客区") {
            return "游客区"
        }
        return nil
    }

    private var constraintText: String? {
        if searchableText.contains("两个人") || searchableText.contains("2个人") || searchableText.contains("两人") {
            return "两个人"
        }
        if request.answerCount > 0 {
            return "\(request.answerCount) 人已来一句"
        }
        if request.status != .draft {
            return request.status.label
        }
        return nil
    }

    private var trimmedContextLine: String? {
        let trimmed = request.context.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { return nil }
        let separators = CharacterSet(charactersIn: "。；;\n")
        let first = trimmed.components(separatedBy: separators).first?.trimmingCharacters(in: .whitespacesAndNewlines)
        guard let first, !first.isEmpty else { return nil }
        return first
    }
}

struct AnswerRequestSquareCard: View {
    let request: HelpRequest
    let reward: String

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            HStack {
                Text("求一个")
                    .font(.system(size: 12, weight: .medium))
                    .tracking(1.6)
                    .foregroundStyle(AppTheme.textMuted)

                Spacer()

                Text(reward)
                    .font(.system(size: 15, weight: .semibold))
                    .foregroundStyle(AppTheme.green)
            }

            Spacer(minLength: 18)

            Text(request.title)
                .font(.system(size: CardTextFitting.requestTitleSize(request.title, compact: true), weight: .semibold))
                .lineSpacing(4)
                .foregroundStyle(AppTheme.text)
                .lineLimit(3)
                .minimumScaleFactor(0.82)

            Text(request.context)
                .font(.system(size: 15))
                .lineSpacing(6)
                .foregroundStyle(AppTheme.textSecondary)
                .lineLimit(3)
                .padding(.top, 18)

            Spacer(minLength: 18)

            HStack(spacing: 8) {
                Image(systemName: "quote.bubble")
                    .font(.system(size: 13, weight: .medium))

                Text("只要来一句")
                    .font(.system(size: 13, weight: .medium))

                Spacer()

                Text("写完即送")
                    .font(.system(size: 12, weight: .medium))
                    .foregroundStyle(AppTheme.textMuted)
            }
            .foregroundStyle(AppTheme.text)
            .padding(.horizontal, 13)
            .padding(.vertical, 10)
            .background(AppTheme.bubble)
            .clipShape(Capsule())
        }
        .padding(22)
        .frame(maxWidth: .infinity)
        .aspectRatio(1, contentMode: .fit)
        .background(AppTheme.card)
        .clipShape(RoundedRectangle(cornerRadius: 24, style: .continuous))
        .overlay(
            RoundedRectangle(cornerRadius: 24, style: .continuous)
                .stroke(AppTheme.border, lineWidth: 1)
        )
        .shadow(color: .black.opacity(0.06), radius: 24, x: 0, y: 10)
        .accessibilityElement(children: .combine)
        .accessibilityLabel("求一个, \(request.title), \(reward)")
    }
}

struct PageIntro: View {
    let title: String
    let subtitle: String

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text(title)
                .font(.system(size: 26, weight: .semibold))
                .foregroundStyle(AppTheme.text)

            Text(subtitle)
                .font(.system(size: 14))
                .lineSpacing(4)
                .foregroundStyle(AppTheme.textSecondary)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(.top, 4)
        .padding(.bottom, 20)
    }
}

struct PrimaryButton: View {
    let title: String
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            Text(title)
                .font(.system(size: 15, weight: .medium))
                .foregroundStyle(AppTheme.onPrimaryAction)
                .frame(maxWidth: .infinity)
                .frame(height: 52)
                .background(AppTheme.primaryAction)
                .clipShape(Capsule())
                .shadow(color: .black.opacity(0.1), radius: 14, x: 0, y: 8)
        }
        .buttonStyle(.plain)
        .accessibilityLabel(title)
    }
}

struct ToastView: View {
    let message: String
    let isVisible: Bool

    var body: some View {
        VStack {
            Spacer()
            Text(message)
                .font(.system(size: 13))
                .foregroundStyle(AppTheme.onPrimaryAction)
                .padding(.horizontal, 16)
                .padding(.vertical, 10)
                .background(AppTheme.primaryAction)
                .clipShape(Capsule())
                .opacity(isVisible ? 1 : 0)
                .offset(y: isVisible ? 0 : 8)
                .animation(.easeOut(duration: 0.22), value: isVisible)
        }
        .padding(.bottom, 110)
        .allowsHitTesting(false)
    }
}

private extension View {
    func cardStyle() -> some View {
        padding(22)
            .background(AppTheme.card)
            .clipShape(RoundedRectangle(cornerRadius: 24, style: .continuous))
            .overlay(
                RoundedRectangle(cornerRadius: 24, style: .continuous)
                    .stroke(AppTheme.border, lineWidth: 1)
            )
            .shadow(color: .black.opacity(0.06), radius: 24, x: 0, y: 10)
    }
}
