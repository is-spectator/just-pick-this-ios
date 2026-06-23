import SwiftUI

struct AppChrome<Content: View, Footer: View>: View {
    let showsBack: Bool
    let backAction: (() -> Void)?
    let onHistory: (() -> Void)?
    let onNewConversation: (() -> Void)?
    let onAnswerEntry: (() -> Void)?
    let onAccountEntry: (() -> Void)?
    @ViewBuilder let content: Content
    @ViewBuilder let footer: Footer

    @Environment(\.dismiss) private var dismiss

    init(
        showsBack: Bool,
        backAction: (() -> Void)?,
        onHistory: (() -> Void)? = nil,
        onNewConversation: (() -> Void)? = nil,
        onAnswerEntry: (() -> Void)? = nil,
        onAccountEntry: (() -> Void)? = nil,
        @ViewBuilder content: () -> Content,
        @ViewBuilder footer: () -> Footer
    ) {
        self.showsBack = showsBack
        self.backAction = backAction
        self.onHistory = onHistory
        self.onNewConversation = onNewConversation
        self.onAnswerEntry = onAnswerEntry
        self.onAccountEntry = onAccountEntry
        self.content = content()
        self.footer = footer()
    }

    var body: some View {
        VStack(spacing: 0) {
            TopBar(
                showsBack: showsBack,
                onHistory: onHistory,
                onNewConversation: onNewConversation,
                onAnswerEntry: onAnswerEntry,
                onAccountEntry: onAccountEntry
            ) {
                if let backAction {
                    backAction()
                } else {
                    dismiss()
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
    let onAnswerEntry: (() -> Void)?
    let onAccountEntry: (() -> Void)?
    let onBack: () -> Void

    var body: some View {
        if showsBack {
            HStack {
                Button(action: onBack) {
                    Image(systemName: "chevron.left")
                        .font(.system(size: 22, weight: .medium))
                        .foregroundStyle(AppTheme.text)
                        .frame(width: 36, height: 36, alignment: .leading)
                }
                .accessibilityLabel("返回")

                Spacer()

                Text("就选这个")
                    .font(.system(size: 15, weight: .semibold))
                    .foregroundStyle(AppTheme.text)

                Spacer()

                Color.clear
                    .frame(width: 36, height: 36)
            }
            .padding(.horizontal, 16)
            .frame(height: 50)
        } else {
            HStack(spacing: 14) {
                Text("皮皮")
                    .font(.system(size: 22, weight: .semibold))
                    .foregroundStyle(AppTheme.text)
                    .accessibilityAddTraits(.isHeader)

                Spacer()

                Button(action: { onHistory?() }) {
                    Image(systemName: "clock.arrow.circlepath")
                        .font(.system(size: 20, weight: .medium))
                        .foregroundStyle(AppTheme.text)
                        .frame(width: 44, height: 44)
                }
                .buttonStyle(.plain)
                .accessibilityLabel("历史")

                Button(action: { onNewConversation?() }) {
                    HStack(spacing: 5) {
                        Image(systemName: "plus.message")
                            .font(.system(size: 15, weight: .semibold))
                        Text("新对话")
                            .font(.system(size: 14, weight: .semibold))
                    }
                    .foregroundStyle(AppTheme.text)
                    .padding(.horizontal, 12)
                    .frame(height: 36)
                    .background(AppTheme.bubble)
                    .clipShape(Capsule())
                }
                .buttonStyle(.plain)
                .accessibilityLabel("新对话")

                Button(action: { onAnswerEntry?() }) {
                    Image(systemName: "bubble.left.and.bubble.right")
                        .font(.system(size: 20, weight: .medium))
                        .foregroundStyle(AppTheme.text)
                        .frame(width: 44, height: 44)
                }
                .buttonStyle(.plain)
                .accessibilityLabel("来一句")
            }
            .padding(.horizontal, 18)
            .frame(height: 56)
        }
    }
}

struct BottomComposer: View {
    @Binding var text: String
    let placeholder: String
    let isSending: Bool
    let onSend: () -> Void

    @FocusState private var isFocused: Bool

    private var canSend: Bool {
        !isSending && !text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
    }

    private func send() {
        guard canSend else { return }
        isFocused = false
        onSend()
    }

    init(
        text: Binding<String>,
        placeholder: String,
        isSending: Bool = false,
        onSend: @escaping () -> Void
    ) {
        self._text = text
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
                            .tint(Color.white)
                            .scaleEffect(0.74)
                    } else {
                        Image(systemName: "arrow.up")
                            .font(.system(size: 17, weight: .semibold))
                            .foregroundStyle(canSend ? Color.white : Color(red: 181 / 255, green: 181 / 255, blue: 181 / 255))
                    }
                }
                .frame(width: 32, height: 32)
                .background(canSend || isSending ? AppTheme.text : AppTheme.disabled)
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
        .frame(minHeight: 60)
        .background(AppTheme.card)
        .clipShape(Capsule())
        .overlay(
            Capsule()
                .stroke(isFocused ? AppTheme.text.opacity(0.9) : AppTheme.border, lineWidth: 1)
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
                }
                .font(.system(size: 15, weight: .semibold))
                .accessibilityLabel("收起键盘")
            }
        }
        .onChange(of: isSending) { _, sending in
            if sending {
                isFocused = false
            }
        }
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

struct DecisionCard: View {
    let pick: TopPick
    let isFollowingUp: Bool
    let isAccepting: Bool
    let onFollowup: (String) -> Void
    let onAskHuman: () -> Void
    let onReject: () -> Void
    let onAccept: () -> Void

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
                    .font(.system(size: imageURL == nil ? 34 : 31, weight: .bold))
                    .lineSpacing(3)
                    .foregroundStyle(AppTheme.text)
                    .lineLimit(3)
                    .minimumScaleFactor(0.82)

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

                Button(action: onAccept) {
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
                }
                .buttonStyle(.plain)
                .disabled(isAccepting)
                .accessibilityLabel("就这个")
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
            .clipShape(RoundedRectangle(cornerRadius: 22, style: .continuous))
            .clipped()
        }
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
                .font(.system(size: 22, weight: .semibold))
                .lineSpacing(2)
                .foregroundStyle(AppTheme.text)
                .padding(.top, 14)

            Text(request.context)
                .font(.system(size: 13))
                .lineSpacing(4)
                .foregroundStyle(AppTheme.textSecondary)
                .padding(.top, 12)

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
                .font(.system(size: 28, weight: .semibold))
                .lineSpacing(4)
                .foregroundStyle(AppTheme.text)
                .lineLimit(3)
                .minimumScaleFactor(0.82)

            Text(request.context)
                .font(.system(size: 15))
                .lineSpacing(6)
                .foregroundStyle(AppTheme.textSecondary)
                .lineLimit(4)
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
                .foregroundStyle(Color.white)
                .frame(maxWidth: .infinity)
                .frame(height: 52)
                .background(AppTheme.text)
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
                .foregroundStyle(Color.white)
                .padding(.horizontal, 16)
                .padding(.vertical, 10)
                .background(AppTheme.text)
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
